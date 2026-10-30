"""FastAPI server: start fix runs, stream their progress over SSE, receive GitHub CI failure webhooks."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import hosted
from .agent import AutoFixAgent, FixRequest
from .config import settings
from .llm import LLM

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
FRONTEND_DIST = ROOT / "frontend" / "dist"
PUBLIC_MODE = os.environ.get("AUTOFIX_PUBLIC_MODE") == "1"
DEFAULT_TEST_COMMAND = os.environ.get("AUTOFIX_DEFAULT_TEST_COMMAND", "python -m pytest -q")

app = FastAPI(title="AutoFixAI")
executor = ThreadPoolExecutor(max_workers=int(os.environ.get("AUTOFIX_WORKERS", "2")))


class Run:
    def __init__(self, req: FixRequest, source: str):
        self.id = uuid.uuid4().hex[:12]
        self.req = req
        self.source = source
        self.status = "queued"
        self.created = time.time()
        self.events: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            self.events.append({"seq": len(self.events), "t": round(time.time() - self.created, 2),
                                "kind": kind, **data})

    def summary(self) -> dict[str, Any]:
        return {"id": self.id, "repo": self.req.repo, "test_command": self.req.test_command,
                "status": self.status, "source": self.source, "created": self.created,
                "result_status": self.result and self.result.get("status")}


RUNS: dict[str, Run] = {}
LIMITER = hosted.RateLimiter()


def _execute(run: Run) -> None:
    run.status = "running"
    try:
        agent = AutoFixAgent(LLM.from_settings(), run.emit)
        result = agent.run(run.req)
        run.result = dataclasses.asdict(result)
        run.status = "completed"
    except Exception as e:
        run.emit("error", {"message": f"{type(e).__name__}: {e}"})
        run.result = {"status": "error", "error": str(e)}
        run.status = "completed"
    run.emit("end", {"result": run.result})


def start_run(req: FixRequest, source: str) -> Run:
    run = Run(req, source)
    RUNS[run.id] = run
    for old in sorted(RUNS.values(), key=lambda r: r.created)[:-200]:  # keep memory bounded
        if old.status == "completed":
            RUNS.pop(old.id, None)
    executor.submit(_execute, run)
    return run


def list_demos() -> list[dict[str, Any]]:
    demos = []
    for d in sorted(EXAMPLES.iterdir()) if EXAMPLES.exists() else []:
        meta_file = d / "autofix.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            demos.append({"id": d.name, **meta})
    return demos


# ------------------------------------------------------------------ API


class RunIn(BaseModel):
    repo: str | None = None
    demo: str | None = None
    test_command: str | None = None
    ref: str | None = None
    ci_log: str | None = None
    allow_test_edits: bool = False
    open_pr: bool = False
    setup_command: str | None = None


@app.get("/api/health")
def health() -> dict[str, Any]:
    info: dict[str, Any] = {
        "ok": True,
        "public_mode": PUBLIC_MODE,
        "nebius_configured": bool(settings.api_key),
        "github_configured": bool(settings.github_token),
        "tavily_configured": bool(settings.tavily_api_key),
        "base_url": settings.base_url,
        "user_repos": hosted.limits() if PUBLIC_MODE else {"enabled": True},
    }
    if settings.api_key:
        try:
            info["models"] = LLM.from_settings().models
        except Exception as e:
            info["models_error"] = str(e)
    return info


@app.get("/api/demos")
def demos() -> list[dict[str, Any]]:
    return list_demos()


@app.post("/api/runs")
def create_run(body: RunIn, request: Request) -> dict[str, Any]:
    try:
        return _create_run(body, request)
    except hosted.Rejected as e:
        raise HTTPException(e.status, e.message)


def _create_run(body: RunIn, request: Request) -> dict[str, Any]:
    visitor_repo = None
    if PUBLIC_MODE:
        if sum(1 for r in RUNS.values() if r.status != "completed") >= hosted.MAX_QUEUED:
            raise hosted.Rejected(503, "The hosted demo is busy. Try again in a minute.")
        user_repo = not body.demo
        if user_repo:
            if not hosted.ALLOW_USER_REPOS:
                raise hosted.Rejected(403, "This public instance only runs the bundled demo repositories.")
            visitor_repo = hosted.parse(body.repo, body.ref, body.test_command, body.setup_command, body.ci_log)
        LIMITER.check(hosted.client_ip(request.headers, request.client and request.client.host), user_repo)
        if visitor_repo:
            hosted.check_remote(visitor_repo)

    if body.demo:
        demo = next((d for d in list_demos() if d["id"] == body.demo), None)
        if not demo:
            raise HTTPException(404, "Unknown demo")
        req = FixRequest(repo=str(EXAMPLES / body.demo), test_command=demo["test_command"],
                         allow_test_edits=False)
        return start_run(req, "demo").summary()

    if PUBLIC_MODE:
        # Visitor repo: public GitHub only, validated, sandboxed, no PRs, capped attempts.
        repo = visitor_repo
        req = FixRequest(repo=repo.url, ref=repo.ref, test_command=repo.test_command,
                         setup_command=repo.setup_command, ci_log=repo.ci_log,
                         allow_test_edits=body.allow_test_edits, open_pr=False,
                         max_attempts=hosted.USER_REPO_MAX_ATTEMPTS)
        return start_run(req, "visitor").summary()

    if not body.repo:
        raise HTTPException(400, "Provide a repo (git URL or local path) or a demo id")
    req = FixRequest(repo=body.repo, test_command=body.test_command or DEFAULT_TEST_COMMAND,
                     ref=body.ref or None, ci_log=body.ci_log or None, setup_command=body.setup_command or None,
                     allow_test_edits=body.allow_test_edits, open_pr=body.open_pr)
    return start_run(req, "manual").summary()


@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    return [r.summary() for r in sorted(RUNS.values(), key=lambda r: r.created, reverse=True)]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = RUNS.get(run_id) or _404()
    return {**run.summary(), "events": run.events, "result": run.result}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request) -> StreamingResponse:
    run = RUNS.get(run_id) or _404()

    async def gen():
        sent = 0
        while True:
            if await request.is_disconnected():
                return
            events = run.events
            while sent < len(events):
                yield f"data: {json.dumps(events[sent])}\n\n"
                sent += 1
            if run.status == "completed" and sent >= len(run.events):
                return
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/github/webhook")
async def github_webhook(request: Request) -> dict[str, Any]:
    """Point a GitHub repo webhook ("Workflow runs" events) here to auto-fix failing CI."""
    raw = await request.body()
    if settings.github_webhook_secret:
        expected = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("X-Hub-Signature-256", "")):
            raise HTTPException(401, "Bad signature")
    if request.headers.get("X-GitHub-Event") != "workflow_run":
        return {"ignored": "not a workflow_run event"}

    payload = json.loads(raw)
    wr = payload.get("workflow_run", {})
    if payload.get("action") != "completed" or wr.get("conclusion") != "failure":
        return {"ignored": "run did not fail"}
    if (wr.get("head_branch") or "").startswith("autofix/"):
        return {"ignored": "failure on an AutoFixAI branch"}

    from .github import failed_job_log

    repo = payload["repository"]
    owner, name = repo["owner"]["login"], repo["name"]
    try:
        log = failed_job_log(owner, name, wr["id"])
    except Exception:
        log = ""
    req = FixRequest(repo=repo["clone_url"], ref=wr.get("head_branch"), ci_log=log or None,
                     test_command=request.query_params.get("test_command") or DEFAULT_TEST_COMMAND,
                     open_pr=True)
    return start_run(req, "github").summary()


def _404():
    raise HTTPException(404, "Run not found")


# ------------------------------------------------------------------ frontend

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = FRONTEND_DIST / path
        if path and file.is_file() and FRONTEND_DIST in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
