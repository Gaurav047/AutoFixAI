"""Command-line entry point.

    python -m autofix fix <repo-or-path> --test "pytest -q" [--pr] [--ci-log failing.log]
    python -m autofix models
    python -m autofix serve
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import settings

COLORS = {"research": "\033[94m", "stage": "\033[36m", "tool": "\033[90m", "edit": "\033[33m", "tests": "\033[35m",
          "error": "\033[31m", "finish": "\033[32m", "lesson": "\033[34m", "thought": "\033[37m"}
RESET = "\033[0m"


def print_event(kind: str, d: dict[str, Any]) -> None:
    c = COLORS.get(kind, "")
    if kind == "stage":
        line = f"==> {d.get('message')}"
    elif kind == "tool":
        line = f"    {d['name']}: {d.get('summary', '')}"
    elif kind == "edit":
        line = f"    edit {d['path']}"
    elif kind == "tests":
        label = "baseline" if d.get("baseline") else "verification" if d.get("verification") else "run"
        line = f"    tests ({label}): {'PASS' if d['passed'] else 'FAIL'} (exit {d['exit_code']})"
    elif kind == "triage":
        line = f"    triage: [{d.get('category')}] {d.get('summary')}\n    suspects: {d.get('suspect_files')}"
    elif kind == "thought":
        line = "    " + d["text"].replace("\n", "\n    ")[:600]
    elif kind == "research":
        if d.get("error"):
            line = f"    tavily ({d['origin']}): search failed: {d['error']}"
        else:
            srcs = "\n".join(f"      - {s['title']} <{s['url']}>" for s in d.get("sources", [])[:5])
            answer = (d.get("answer") or "")[:300]
            line = f"    tavily ({d['origin']}): \"{d['query']}\"\n      {answer}\n{srcs}"
    elif kind == "finish":
        line = f"    root cause: {d.get('root_cause')}\n    fix: {d.get('fix_summary')}"
    elif kind in ("lesson", "attempt_failed", "blocked", "error", "pr"):
        line = f"    {kind}: {d.get('text') or d.get('reason') or d.get('message') or d.get('url') or d}"
    else:
        return
    print(f"{c}{line}{RESET}", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="autofix", description="AutoFixAI: autonomous CI repair with NVIDIA Nemotron")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fix", help="Fix the failing tests in a repository")
    f.add_argument("repo", help="GitHub URL or local path")
    f.add_argument("--test", default="python -m pytest -q", help="Test command to make pass")
    f.add_argument("--ref", help="Branch to check out (git URLs only)")
    f.add_argument("--ci-log", type=Path, help="File containing the failing CI log")
    f.add_argument("--allow-test-edits", action="store_true")
    f.add_argument("--pr", action="store_true", help="Open a GitHub pull request with the fix")
    f.add_argument("--out", type=Path, help="Write the resulting patch to this file")

    sub.add_parser("models", help="Show which Nemotron model each tier resolves to")
    s = sub.add_parser("serve", help="Run the web dashboard + API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("autofix.server:app", host=args.host, port=args.port)
        return 0

    from .llm import LLM

    llm = LLM.from_settings()
    if args.cmd == "models":
        print(f"Token Factory: {settings.base_url}")
        for tier, model in llm.models.items():
            print(f"  {tier:<6} -> {model}")
        return 0

    from .agent import AutoFixAgent, FixRequest

    req = FixRequest(
        repo=args.repo, test_command=args.test, ref=args.ref,
        ci_log=args.ci_log.read_text(encoding="utf-8", errors="replace") if args.ci_log else None,
        allow_test_edits=args.allow_test_edits, open_pr=args.pr,
    )
    result = AutoFixAgent(llm, print_event).run(req)

    print()
    print(f"Result: {result.status}  ({result.attempts} attempt(s), {result.seconds}s)")
    if result.pr:
        print(f"\nPR: {result.pr.get('title')}\n\n{result.pr.get('body')}")
    if result.diff:
        print("\n" + result.diff)
        if args.out:
            args.out.write_text(result.diff, encoding="utf-8")
            print(f"Patch written to {args.out}")
    if result.pr_url:
        print(f"Pull request: {result.pr_url}")
    print("Token usage by tier:")
    print(json.dumps(result.usage, indent=2))
    return 0 if result.status in ("fixed", "already_passing") else 1


if __name__ == "__main__":
    sys.exit(main())
