"""An isolated working copy of the target repository, plus the sandboxed operations the agent may perform on it.

Every path the agent supplies is resolved inside the workspace root; it cannot read or write outside it.
The only command the agent can execute is the repository's configured test command.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import settings

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    "dist", "build", ".next", ".tox", "target", ".idea", ".vscode",
}
MAX_READ_CHARS = 24_000
MAX_OUTPUT_CHARS = 12_000


class WorkspaceError(Exception):
    pass


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if check and proc.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _truncate_middle(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n\n... [{len(text) - limit} chars truncated] ...\n\n{text[-half:]}"


@dataclass
class TestResult:
    passed: bool
    exit_code: int
    output: str
    timed_out: bool = False


class Workspace:
    def __init__(self, root: Path, test_command: str):
        self.root = root.resolve()
        self.test_command = test_command
        self.baseline = "HEAD"

    # ---------- creation ----------

    @classmethod
    def create(cls, source: str, test_command: str, ref: str | None = None) -> "Workspace":
        """Clone a git URL, or copy a local directory, into a fresh run directory."""
        settings.work_dir.mkdir(parents=True, exist_ok=True)
        dest = settings.work_dir / f"ws-{uuid.uuid4().hex[:10]}"

        if re.match(r"^(https?://|git@)", source):
            url = source
            if settings.github_token and url.startswith("https://github.com/"):
                url = url.replace("https://", f"https://x-access-token:{settings.github_token}@", 1)
            args = ["clone", "--depth", "50"]
            if ref:
                args += ["--branch", ref]
            _git(settings.work_dir, *args, url, str(dest))
        else:
            src = Path(source).expanduser().resolve()
            if not src.is_dir():
                raise WorkspaceError(f"Repository path not found: {src}")
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*(SKIP_DIRS - {".git"})))

        ws = cls(dest, test_command)
        fresh = not (dest / ".git").exists()
        if fresh:
            _git(dest, "init", "-q")
        # Keep test-run byproducts (caches, build output) out of the diff.
        exclude = dest / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        patterns = [f"{d}/" for d in sorted(SKIP_DIRS - {".git"})] + ["*.pyc", "autofix.json"]
        with exclude.open("a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(patterns) + "\n")
        if fresh:
            _git(dest, "add", "-A")
            _git(dest, "-c", "user.name=autofix", "-c", "user.email=autofix@local",
                 "commit", "-q", "-m", "baseline", "--allow-empty")
        ws.baseline = _git(dest, "rev-parse", "HEAD").strip()
        return ws

    # ---------- path safety ----------

    def resolve(self, rel: str) -> Path:
        rel = rel.strip().lstrip("/\\") or "."
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise WorkspaceError(f"Path escapes workspace: {rel}")
        if ".git" in path.relative_to(self.root).parts:
            raise WorkspaceError("Access to .git is not allowed")
        return path

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    # ---------- agent tools ----------

    def list_files(self, subdir: str = ".", limit: int = 400) -> list[str]:
        base = self.resolve(subdir)
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                out.append(self.rel(Path(dirpath) / name))
                if len(out) >= limit:
                    return out
        return out

    def read_file(self, path: str, start: int = 1, end: int | None = None) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise WorkspaceError(f"Not a file: {path}")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start)
        end = min(len(lines), end or len(lines))
        numbered = "\n".join(f"{i:>5}| {lines[i - 1]}" for i in range(start, end + 1))
        return _truncate_middle(numbered, MAX_READ_CHARS) or "(empty file)"

    def search(self, pattern: str, glob: str | None = None, limit: int = 60) -> list[str]:
        try:
            rx = re.compile(pattern)
        except re.error:
            rx = re.compile(re.escape(pattern))
        hits: list[str] = []
        for rel in self.list_files(limit=5000):
            if glob and not Path(rel).match(glob):
                continue
            try:
                text = (self.root / rel).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{n}: {line.strip()[:200]}")
                    if len(hits) >= limit:
                        return hits
        return hits

    def edit_file(self, path: str, old: str, new: str) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise WorkspaceError(f"Not a file: {path}")
        text = p.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            raise WorkspaceError("old_text not found. Re-read the file and copy the exact text, including indentation.")
        if count > 1:
            raise WorkspaceError(f"old_text matches {count} places. Include more surrounding lines so it is unique.")
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        return f"Edited {self.rel(p)}"

    def write_file(self, path: str, content: str) -> str:
        p = self.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {self.rel(p)} ({len(content)} chars)"

    def run_tests(self) -> TestResult:
        cmd = self.test_command
        if os.environ.get("AUTOFIX_SANDBOX") == "docker":
            image = os.environ.get("AUTOFIX_DOCKER_IMAGE", "python:3.12-slim")
            argv = ["docker", "run", "--rm", "--network", os.environ.get("AUTOFIX_DOCKER_NETWORK", "none"),
                    "--memory", "2g", "--cpus", "2", "-v", f"{self.root}:/work", "-w", "/work",
                    image, "sh", "-c", cmd]
            shell = False
        else:
            argv, shell = cmd, True
        try:
            proc = subprocess.run(
                argv, cwd=self.root, shell=shell, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=settings.test_timeout_s,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "CI": "true",
                     # `python` in the test command resolves to the interpreter running AutoFixAI
                     "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")},
            )
        except subprocess.TimeoutExpired as e:
            out = "".join(
                x.decode("utf-8", "replace") if isinstance(x, bytes) else x
                for x in (e.stdout or "", e.stderr or "")
            )
            return TestResult(False, -1, _truncate_middle(out + "\n[timed out]", MAX_OUTPUT_CHARS), True)
        output = _truncate_middle((proc.stdout or "") + (proc.stderr or ""), MAX_OUTPUT_CHARS)
        return TestResult(proc.returncode == 0, proc.returncode, output)

    # ---------- results ----------

    def diff(self) -> str:
        _git(self.root, "add", "-A")
        return _git(self.root, "diff", "--cached", self.baseline, "--", ".")

    def changed_files(self) -> list[str]:
        _git(self.root, "add", "-A")
        out = _git(self.root, "diff", "--cached", "--name-only", self.baseline)
        return [line for line in out.splitlines() if line]

    def reset(self) -> None:
        _git(self.root, "reset", "-q", "--hard", self.baseline)
        _git(self.root, "clean", "-fdq")

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
