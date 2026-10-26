"""Tool definitions exposed to the Nemotron coding agent, and their dispatcher."""

from __future__ import annotations

import json
from typing import Any, Callable

from . import research
from .workspace import Workspace, WorkspaceError


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SPECS: list[dict[str, Any]] = [
    _fn("list_files", "List files in the repository (or a subdirectory).",
        {"path": {"type": "string", "description": "Directory relative to repo root. Default '.'"}}, []),
    _fn("read_file", "Read a file with line numbers. Use start/end to read part of a large file.",
        {"path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}}, ["path"]),
    _fn("search", "Regex search across repository files. Returns file:line: text matches.",
        {"pattern": {"type": "string"}, "glob": {"type": "string", "description": "e.g. '*.py'"}}, ["pattern"]),
    _fn("edit_file",
        "Replace one exact, unique occurrence of old_text with new_text in a file. "
        "old_text must match the file byte-for-byte including indentation.",
        {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
        ["path", "old_text", "new_text"]),
    _fn("write_file", "Create a new file or fully overwrite an existing one.",
        {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _fn("run_tests", "Run the repository's test command and return pass/fail plus output.", {}, []),
    _fn("finish",
        "Call when the tests pass (or you are certain you cannot fix it). Summarise root cause and fix.",
        {"root_cause": {"type": "string"}, "fix_summary": {"type": "string"},
         "confident": {"type": "boolean"}},
        ["root_cause", "fix_summary"]),
]

WEB_SEARCH_SPEC = _fn(
    "web_search",
    "Search the web (Tavily) for an error message, library changelog, or API deprecation. "
    "Use when the failure involves third-party library behaviour you are unsure about.",
    {"query": {"type": "string"}},
    ["query"],
)


def tool_specs() -> list[dict[str, Any]]:
    specs = list(TOOL_SPECS)
    if research.enabled():
        specs.insert(-1, WEB_SEARCH_SPEC)
    return specs


class ToolBox:
    """Executes tool calls against a workspace and reports each call to an event sink."""

    def __init__(self, ws: Workspace, emit: Callable[[str, dict[str, Any]], None],
                 web: research.Research | None = None):
        self.ws = ws
        self.emit = emit
        self.web = web
        self.last_test = None

    def call(self, name: str, raw_args: str | dict[str, Any] | None) -> str:
        try:
            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
        except json.JSONDecodeError as e:
            return f"ERROR: arguments were not valid JSON ({e}). Retry with valid JSON."
        try:
            result = self._dispatch(name, args)
        except WorkspaceError as e:
            result = f"ERROR: {e}"
        except Exception as e:  # tool failures are reported back to the model, not raised
            result = f"ERROR: {type(e).__name__}: {e}"
        return result

    def _dispatch(self, name: str, a: dict[str, Any]) -> str:
        ws = self.ws
        if name == "list_files":
            files = ws.list_files(a.get("path") or ".")
            self.emit("tool", {"name": name, "summary": f"{len(files)} files"})
            return "\n".join(files) or "(no files)"
        if name == "read_file":
            path = a["path"]
            self.emit("tool", {"name": name, "summary": path})
            return ws.read_file(path, int(a.get("start") or 1), a.get("end") and int(a["end"]))
        if name == "search":
            hits = ws.search(a["pattern"], a.get("glob"))
            self.emit("tool", {"name": name, "summary": f"/{a['pattern']}/ -> {len(hits)} hits"})
            return "\n".join(hits) or "No matches."
        if name == "edit_file":
            msg = ws.edit_file(a["path"], a["old_text"], a["new_text"])
            self.emit("edit", {"path": a["path"], "old": a["old_text"], "new": a["new_text"]})
            return msg
        if name == "write_file":
            msg = ws.write_file(a["path"], a["content"])
            self.emit("edit", {"path": a["path"], "old": "", "new": a["content"][:2000]})
            return msg
        if name == "run_tests":
            self.emit("tests_started", {"command": ws.test_command})
            res = ws.run_tests()
            self.last_test = res
            self.emit("tests", {"passed": res.passed, "exit_code": res.exit_code,
                                "output": res.output[-4000:]})
            status = "PASSED" if res.passed else f"FAILED (exit {res.exit_code})"
            return f"Tests {status}\n\n{res.output}"
        if name == "web_search" and self.web:
            return research.Research.as_text(self.web.search(a["query"], origin="agent"))
        raise WorkspaceError(f"Unknown tool: {name}")
