"""GitHub integration: push the verified fix to a branch and open a pull request."""

from __future__ import annotations

import re
import time

import httpx

from .config import settings
from .workspace import Workspace, _git

_REPO_RE = re.compile(r"github\.com[/:]([^/]+)/([^/.]+?)(?:\.git)?/?$")


def parse_repo(url: str) -> tuple[str, str]:
    m = _REPO_RE.search(url)
    if not m:
        raise ValueError(f"Not a GitHub repository URL: {url}")
    return m.group(1), m.group(2)


def _api(method: str, path: str, **kw) -> httpx.Response:
    resp = httpx.request(
        method, f"https://api.github.com{path}",
        headers={"Authorization": f"Bearer {settings.github_token}",
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        timeout=30, **kw,
    )
    resp.raise_for_status()
    return resp


def open_pull_request(ws: Workspace, repo_url: str, base: str | None, title: str, body: str) -> str:
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    owner, name = parse_repo(repo_url)
    if not base:
        base = _api("GET", f"/repos/{owner}/{name}").json()["default_branch"]

    branch = f"autofix/{time.strftime('%Y%m%d-%H%M%S')}"
    _git(ws.root, "checkout", "-q", "-b", branch)
    _git(ws.root, "add", "-A")
    _git(ws.root, "-c", "user.name=AutoFixAI", "-c", "user.email=autofix-bot@users.noreply.github.com",
         "commit", "-q", "-m", title, "-m", "Automated fix generated and verified by AutoFixAI.")
    _git(ws.root, "push", "-q", "origin", branch)

    pr = _api("POST", f"/repos/{owner}/{name}/pulls",
              json={"title": title, "body": body, "head": branch, "base": base}).json()
    return pr["html_url"]


def failed_job_log(owner: str, name: str, run_id: int, max_chars: int = 20000) -> str:
    """Fetch the log of the first failed job in a workflow run (used by the webhook)."""
    jobs = _api("GET", f"/repos/{owner}/{name}/actions/runs/{run_id}/jobs").json().get("jobs", [])
    for job in jobs:
        if job.get("conclusion") == "failure":
            resp = httpx.get(
                f"https://api.github.com/repos/{owner}/{name}/actions/jobs/{job['id']}/logs",
                headers={"Authorization": f"Bearer {settings.github_token}"},
                follow_redirects=True, timeout=60,
            )
            if resp.status_code == 200:
                return resp.text[-max_chars:]
    return ""
