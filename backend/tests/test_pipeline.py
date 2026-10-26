"""Offline end-to-end tests: a scripted fake LLM drives the real pipeline, workspace, and tools."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ["AUTOFIX_ESCALATE_AFTER"] = "1"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from autofix.agent import AutoFixAgent, FixRequest  # noqa: E402
from autofix.config import settings  # noqa: E402
from autofix.llm import LLM, Usage, parse_json, strip_thinking  # noqa: E402
from autofix.workspace import Workspace, WorkspaceError  # noqa: E402

EXAMPLE = ROOT / "examples" / "inventory-refactor"
TEST_CMD = f'"{sys.executable}" -m pytest -q -p no:cacheprovider'


def tool_msg(name: str, **args):
    call = SimpleNamespace(id=f"call_{name}_{len(args)}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    return SimpleNamespace(content=None, tool_calls=[call])


def text_msg(text: str):
    return SimpleNamespace(content=text, tool_calls=None)


class FakeLLM(LLM):
    def __init__(self, script: dict[str, list]):
        self.client = None
        self.models = {"nano": "fake-nano", "super": "fake-super", "ultra": "fake-ultra"}
        self.usage = {t: Usage() for t in self.models}
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []

    def chat(self, tier, messages, **kw):
        self.calls.append(tier)
        self.usage[tier].calls += 1
        return self.script[tier].pop(0)


TRIAGE = text_msg('<think>hmm</think>```json\n{"category": "api_change", "summary": "refactor broke service", '
                  '"failing_tests": [], "suspect_files": ["inventory/service.py", "nope.py"], '
                  '"hypothesis": "stale field name", "difficulty": "easy"}\n```')
WRITEUP = text_msg('{"title": "fix(inventory): finish v2 refactor", "body": "## Root cause\\nstale callers"}')

GOOD_FIX = [
    tool_msg("read_file", path="inventory/service.py"),
    tool_msg("edit_file", path="inventory/service.py", old_text="        product.qty += amount\n        return product.qty",
             new_text="        product.stock += amount\n        return product.stock"),
    tool_msg("edit_file", path="inventory/service.py", old_text="bulk_price(product.unit_price, quantity)",
             new_text="bulk_price(quantity, product.unit_price)"),
    tool_msg("run_tests"),
    tool_msg("finish", root_cause="callers not updated for v2 refactor", fix_summary="use stock and new arg order"),
]


def run(script):
    events = []
    llm = FakeLLM(script)
    agent = AutoFixAgent(llm, lambda kind, data: events.append((kind, data)))
    result = agent.run(FixRequest(repo=str(EXAMPLE), test_command=TEST_CMD))
    return result, events, llm


def test_fixes_on_first_attempt():
    result, events, llm = run({"nano": [TRIAGE, WRITEUP], "super": list(GOOD_FIX)})
    assert result.status == "fixed"
    assert result.tier_used == "super"
    assert result.changed_files == ["inventory/service.py"]
    assert "product.stock += amount" in result.diff
    assert result.pr["title"].startswith("fix(inventory)")
    triage = next(d for k, d in events if k == "triage")
    assert triage["suspect_files"] == ["inventory/service.py"]  # hallucinated path filtered out
    # source example is untouched
    assert "product.qty" in (EXAMPLE / "inventory" / "service.py").read_text()


def test_blocks_test_edits_then_escalates_to_ultra():
    cheat = [
        tool_msg("write_file", path="tests/test_service.py", content="def test_ok():\n    pass\n"),
        text_msg("I am done."),
        tool_msg("finish", root_cause="tests were wrong", fix_summary="rewrote tests"),
    ]
    result, events, llm = run({"nano": [TRIAGE, text_msg("- do not touch tests"), WRITEUP],
                               "super": cheat, "ultra": list(GOOD_FIX)})
    assert any(k == "blocked" for k, _ in events)
    assert any(k == "attempt_failed" for k, _ in events)
    assert result.status == "fixed"
    assert result.attempts == 2 and result.tier_used == "ultra"
    assert llm.calls.count("ultra") == len(GOOD_FIX)


def test_workspace_rejects_path_escape(tmp_path):
    ws = Workspace(tmp_path, "true")
    with pytest.raises(WorkspaceError):
        ws.resolve("../outside.txt")
    with pytest.raises(WorkspaceError):
        ws.resolve(".git/config")


def test_parse_helpers():
    assert strip_thinking("<think>x</think> hi") == "hi"
    assert parse_json('Sure:\n{"a": 1} done') == {"a": 1}


def test_settings_loaded():
    assert settings.escalate_after == 1
