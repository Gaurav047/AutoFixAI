"""Offline end-to-end tests: a scripted fake LLM drives the real pipeline, workspace, and tools."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from autofix.agent import AutoFixAgent, FixRequest  # noqa: E402
from autofix.config import settings  # noqa: E402
from autofix.llm import LLM, Usage, parse_json, strip_thinking  # noqa: E402
from autofix.workspace import Workspace, WorkspaceError  # noqa: E402

EXAMPLE = ROOT / "examples" / "inventory-refactor"
TEST_CMD = f'"{sys.executable}" -m pytest -q -p no:cacheprovider'


@pytest.fixture(autouse=True)
def escalate_after_one():
    """Escalate to Ultra after one failed Super attempt (settings is frozen, so patch it directly)."""
    previous = settings.escalate_after
    object.__setattr__(settings, "escalate_after", 1)
    yield
    object.__setattr__(settings, "escalate_after", previous)


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


def test_tavily_research_feeds_agent_and_pr(monkeypatch):
    import autofix.agent
    import autofix.research

    queries = []

    def fake_search(query, max_results=5):
        queries.append(query)
        return {"answer": "distutils was removed in Python 3.12; use packaging.version.Version. "
                          "inspect.getargspec was removed in 3.11; use inspect.getfullargspec.",
                "results": [{"title": "PEP 632 - Deprecate distutils module",
                             "url": "https://peps.python.org/pep-0632/", "content": "distutils is removed in 3.12"},
                            {"title": "What's New In Python 3.11",
                             "url": "https://docs.python.org/3/whatsnew/3.11.html", "content": "getargspec removed"}]}

    monkeypatch.setattr(autofix.research, "enabled", lambda: True)
    monkeypatch.setattr(autofix.agent, "research_enabled", lambda: True)
    monkeypatch.setattr(autofix.research, "tavily_search", fake_search)

    triage = text_msg('{"category": "import_error", "summary": "distutils is gone", "failing_tests": [], '
                      '"suspect_files": ["relkit/versions.py"], "hypothesis": "removed stdlib APIs", '
                      '"difficulty": "easy", "search_query": "distutils LooseVersion removed python 3.12 replacement"}')
    fix = [
        tool_msg("read_file", path="relkit/versions.py"),
        tool_msg("web_search", query="inspect.getargspec removed replacement"),
        tool_msg("edit_file", path="relkit/versions.py", old_text="from distutils.version import LooseVersion",
                 new_text="from packaging.version import Version as LooseVersion"),
        tool_msg("edit_file", path="relkit/hooks.py", old_text="inspect.getargspec(hook)",
                 new_text="inspect.getfullargspec(hook)"),
        tool_msg("run_tests"),
        tool_msg("finish", root_cause="stdlib APIs removed", fix_summary="use packaging and getfullargspec"),
    ]
    events = []
    llm = FakeLLM({"nano": [triage, WRITEUP], "super": fix})
    seen_prompts = []
    original_chat = llm.chat

    def recording_chat(tier, messages, **kw):
        seen_prompts.append(messages[1]["content"] if len(messages) > 1 else "")
        return original_chat(tier, messages, **kw)

    llm.chat = recording_chat
    result = AutoFixAgent(llm, lambda k, d: events.append((k, d))).run(
        FixRequest(repo=str(ROOT / "examples" / "python-upgrade"), test_command=TEST_CMD))

    assert result.status == "fixed"
    assert queries == ["distutils LooseVersion removed python 3.12 replacement", "inspect.getargspec removed replacement"]
    assert [d["origin"] for k, d in events if k == "research"] == ["triage", "agent"]
    assert "Web research (Tavily)" in seen_prompts[1]          # first Super call sees the findings
    assert "## References" in result.pr["body"] and "https://peps.python.org/pep-0632/" in result.pr["body"]
    assert result.usage["tavily"]["searches"] == 2
    assert len(result.research["sources"]) == 2               # de-duplicated across both searches


def test_no_research_for_logic_bugs(monkeypatch):
    import autofix.agent

    monkeypatch.setattr(autofix.agent, "research_enabled", lambda: True)
    assert AutoFixAgent._research_query({"category": "logic_bug", "search_query": "x"}) is None
    assert AutoFixAgent._research_query({"category": "import_error", "search_query": None}) is None
    assert AutoFixAgent._research_query({"category": "api_change", "search_query": " q "}) == "q"


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
