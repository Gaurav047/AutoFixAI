"""Protections for running visitors' repositories on a public deployment.

Visitors can submit their own public GitHub repositories when AUTOFIX_ALLOW_USER_REPOS=1. Their code then runs
on this server, so every request is validated and rate-limited here, and commands run in the `user` sandbox
(see workspace.py). Nothing a visitor submits can open a pull request or read a local path.
"""

from __future__ import annotations

import os
import re
import socket
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import httpx


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# "1" or "auto": enable visitor repos once the network guard is verified; "0": demos only.
REQUESTED = os.environ.get("AUTOFIX_ALLOW_USER_REPOS", "0") in ("1", "auto")
ALLOW_USER_REPOS = False                       # flipped on only by enable_if_safe()
STATUS_REASON = "checking the sandbox network guard" if REQUESTED else "disabled by configuration"
MAX_REPO_MB = _int("AUTOFIX_MAX_REPO_MB", 50)
RUNS_PER_IP_PER_HOUR = _int("AUTOFIX_RUNS_PER_IP_HOUR", 5)
USER_REPO_RUNS_PER_DAY = _int("AUTOFIX_USER_REPO_RUNS_PER_DAY", 40)
MAX_QUEUED = _int("AUTOFIX_MAX_QUEUED", 6)
USER_REPO_MAX_ATTEMPTS = _int("AUTOFIX_USER_REPO_MAX_ATTEMPTS", 2)

REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")
REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
MAX_COMMAND_LEN = 300
MAX_CI_LOG_LEN = 20_000


class Rejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class UserRepo:
    url: str
    ref: str | None
    test_command: str
    setup_command: str | None
    ci_log: str | None


def _command(value: str | None, field: str, required: bool) -> str | None:
    value = (value or "").strip()
    if not value:
        if required:
            raise Rejected(400, f"{field} is required")
        return None
    if len(value) > MAX_COMMAND_LEN or "\n" in value or "\r" in value:
        raise Rejected(400, f"{field} must be a single line of at most {MAX_COMMAND_LEN} characters")
    return value


def parse(repo: str | None, ref: str | None, test_command: str | None,
          setup_command: str | None, ci_log: str | None) -> UserRepo:
    """Validate the request without any network calls (so typos don't cost rate-limit budget)."""
    url = (repo or "").strip()
    m = REPO_RE.match(url)
    if not m:
        raise Rejected(400, "Enter a public GitHub repository URL, like https://github.com/owner/repo")
    ref = (ref or "").strip() or None
    if ref and (not REF_RE.match(ref) or ".." in ref or ref.startswith("-")):
        raise Rejected(400, "Branch name contains unsupported characters")
    if ci_log and len(ci_log) > MAX_CI_LOG_LEN:
        ci_log = ci_log[-MAX_CI_LOG_LEN:]
    return UserRepo(
        url=f"https://github.com/{m.group(1)}/{m.group(2)}",
        ref=ref,
        test_command=_command(test_command, "Test command", required=True),
        setup_command=_command(setup_command, "Setup command", required=False),
        ci_log=ci_log or None,
    )


def check_remote(repo: UserRepo) -> None:
    """Confirm with GitHub that the repository exists, is public, and is small enough."""
    owner, name = repo.url.split("/")[-2:]
    try:
        resp = httpx.get(f"https://api.github.com/repos/{owner}/{name}",
                         headers={"Accept": "application/vnd.github+json"}, timeout=15)
    except httpx.HTTPError:
        raise Rejected(503, "Couldn't reach GitHub to check the repository. Try again shortly.")
    if resp.status_code == 404:
        raise Rejected(400, "Repository not found. Only public GitHub repositories are supported.")
    if resp.status_code != 200:
        raise Rejected(503, "GitHub didn't answer the repository check. Try again shortly.")
    info = resp.json()
    if info.get("private"):
        raise Rejected(400, "Only public repositories are supported.")
    size_mb = (info.get("size") or 0) / 1024
    if size_mb > MAX_REPO_MB:
        raise Rejected(400, f"Repository is {size_mb:.0f} MB; this hosted demo accepts up to {MAX_REPO_MB} MB.")


def validate(repo: str | None, ref: str | None, test_command: str | None,
             setup_command: str | None, ci_log: str | None) -> UserRepo:
    parsed = parse(repo, ref, test_command, setup_command, ci_log)
    check_remote(parsed)
    return parsed


class RateLimiter:
    """In-memory sliding windows: runs per client per hour, and visitor-repo runs per day."""

    def __init__(self):
        self._lock = threading.Lock()
        self._per_ip: dict[str, deque[float]] = defaultdict(deque)
        self._user_repo_runs: deque[float] = deque()

    @staticmethod
    def _trim(q: deque[float], window: float, now: float) -> None:
        while q and now - q[0] > window:
            q.popleft()

    def check(self, ip: str, user_repo: bool) -> None:
        now = time.time()
        with self._lock:
            q = self._per_ip[ip]
            self._trim(q, 3600, now)
            if len(q) >= RUNS_PER_IP_PER_HOUR:
                wait = int(3600 - (now - q[0])) // 60 + 1
                raise Rejected(429, f"Rate limit: {RUNS_PER_IP_PER_HOUR} runs per hour. Try again in about {wait} min.")
            if user_repo:
                self._trim(self._user_repo_runs, 86400, now)
                if len(self._user_repo_runs) >= USER_REPO_RUNS_PER_DAY:
                    raise Rejected(429, "The hosted demo has reached today's limit for custom repositories. "
                                        "The demo repos still work, or run AutoFixAI locally.")
                self._user_repo_runs.append(now)
            q.append(now)


def client_ip(headers, fallback: str | None) -> str:
    forwarded = headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or fallback or "unknown"


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def enable_if_safe(port: int, wait_s: float = 60.0) -> None:
    """Turn visitor repos on only if the sandbox is isolated from the metadata service and local network.

    Runs in a background thread after startup: the firewall check probes this server's own port, so the
    server must already be listening (confirmed as root first, as a positive control).
    """
    global ALLOW_USER_REPOS, STATUS_REASON
    from . import netguard
    from .workspace import SANDBOX_MODE

    if not REQUESTED:
        return
    if SANDBOX_MODE != "user":
        STATUS_REASON = "visitor repos require AUTOFIX_SANDBOX=user (the Docker image)"
        return
    deadline = time.time() + wait_s
    while not _listening(port):
        if time.time() > deadline:
            STATUS_REASON = "the server didn't start listening, so the firewall check couldn't run"
            return
        time.sleep(0.5)
    status = netguard.setup(port)
    ALLOW_USER_REPOS = status.ok
    STATUS_REASON = status.reason


def limits() -> dict:
    return {
        "enabled": ALLOW_USER_REPOS,
        "reason": STATUS_REASON,
        "max_repo_mb": MAX_REPO_MB,
        "runs_per_hour": RUNS_PER_IP_PER_HOUR,
        "max_attempts": USER_REPO_MAX_ATTEMPTS,
    }
