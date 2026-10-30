"""An isolated working copy of the target repository, plus the sandboxed operations the agent may perform on it.

Every path the agent supplies is resolved inside the workspace root; it cannot read or write outside it.
The only commands that run are the repository's setup and test commands, never anything the model writes.

Sandbox modes (AUTOFIX_SANDBOX):
  unset   run commands as the current user, with secrets stripped from the environment (local development)
  user    run commands as the unprivileged `sandbox` user with resource limits and a minimal environment;
          the server runs as root, so sandboxed code can't read its API keys (hosted deployment)
  docker  run commands in a throwaway container
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

SANDBOX_MODE = os.environ.get("AUTOFIX_SANDBOX", "")
SANDBOX_USER = os.environ.get("AUTOFIX_SANDBOX_USER", "sandbox")
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)
# Resource limits for sandboxed commands (prlimit): address space, processes, file size, CPU seconds.
LIMITS = ["--as=4294967296", "--nproc=256", "--fsize=1073741824", "--cpu=900"]


class WorkspaceError(Exception):
    pass


def _git(cwd: Path, *args: str, check: bool = True, timeout: int = 120) -> str:
    try:
        proc = subprocess.run(
            ["git", "-c", "safe.directory=*", "-c", "core.hooksPath=/dev/null", *args],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"},
        )
    except subprocess.TimeoutExpired:
        raise WorkspaceError(f"git {args[0]} timed out after {timeout}s")
    if check and proc.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} failed: {proc.stderr.strip()[-500:]}")
    return proc.stdout


def _sandbox_ids() -> tuple[int, int]:
    import pwd  # POSIX only; sandbox mode only runs in the Linux container

    entry = pwd.getpwnam(SANDBOX_USER)
    return entry.pw_uid, entry.pw_gid


def _chown_tree(path: Path) -> None:
    if SANDBOX_MODE != "user":
        return
    uid, gid = _sandbox_ids()
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        os.chown(dirpath, uid, gid)
        for name in filenames:
            os.chown(os.path.join(dirpath, name), uid, gid, follow_symlinks=False)


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
        # Per-run virtualenv for the repo's dependencies, outside the repo so it never shows in the diff.
        self.env_dir = self.root.with_name(self.root.name + "-env")

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
            args = ["-c", "protocol.file.allow=never", "clone", "--depth", "50", "--no-tags",
                    "--single-branch", "--no-recurse-submodules"]
            if ref:
                args += ["--branch", ref]
            _git(settings.work_dir, *args, "--", url, str(dest), timeout=180)
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
        patterns = [f"{d}/" for d in sorted(SKIP_DIRS - {".git"})] + ["*.pyc", "*.egg-info/", "autofix.json"]
        with exclude.open("a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(patterns) + "\n")
        if fresh:
            _git(dest, "add", "-A")
            _git(dest, "-c", "user.name=autofix", "-c", "user.email=autofix@local",
                 "commit", "-q", "-m", "baseline", "--allow-empty")
        ws.baseline = _git(dest, "rev-parse", "HEAD").strip()
        ws._prepare_sandbox()
        return ws

    def _prepare_sandbox(self) -> None:
        """In `user` mode, hand the repo to the sandbox user and give it a private virtualenv."""
        if SANDBOX_MODE != "user":
            return
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(self.env_dir)],
                       check=True, capture_output=True, timeout=120)
        (self.env_dir / "home").mkdir(exist_ok=True)
        _chown_tree(self.root)
        _chown_tree(self.env_dir)
        # .git may hold a credentialed remote URL; sandboxed code must not read it.
        os.chmod(self.root / ".git", 0o700)

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
        _chown_tree(p.parent)
        return f"Edited {self.rel(p)}"

    def write_file(self, path: str, content: str) -> str:
        p = self.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        _chown_tree(p.parent)
        return f"Wrote {self.rel(p)} ({len(content)} chars)"

    def run_tests(self) -> TestResult:
        return self.run_command(self.test_command, settings.test_timeout_s)

    def run_command(self, cmd: str, timeout: int) -> TestResult:
        """Run a repository command (setup or tests) in the configured sandbox."""
        if SANDBOX_MODE == "docker":
            image = os.environ.get("AUTOFIX_DOCKER_IMAGE", "python:3.12-slim")
            argv = ["docker", "run", "--rm", "--network", os.environ.get("AUTOFIX_DOCKER_NETWORK", "none"),
                    "--memory", "2g", "--cpus", "2", "-v", f"{self.root}:/work", "-w", "/work",
                    image, "sh", "-c", cmd]
            env, shell = self._clean_env(), False
        elif SANDBOX_MODE == "user":
            uid, gid = _sandbox_ids()
            argv = ["prlimit", *LIMITS, "--", "setpriv", f"--reuid={uid}", f"--regid={gid}", "--clear-groups",
                    "--no-new-privs", "--", "sh", "-c", cmd]
            env, shell = self._sandbox_env(), False
        else:
            argv, env, shell = cmd, self._clean_env(), True
        try:
            proc = subprocess.run(
                argv, cwd=self.root, shell=shell, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired as e:
            out = "".join(
                x.decode("utf-8", "replace") if isinstance(x, bytes) else x
                for x in (e.stdout or "", e.stderr or "")
            )
            return TestResult(False, -1, _truncate_middle(out + "\n[timed out]", MAX_OUTPUT_CHARS), True)
        output = _truncate_middle((proc.stdout or "") + (proc.stderr or ""), MAX_OUTPUT_CHARS)
        return TestResult(proc.returncode == 0, proc.returncode, output)

    @staticmethod
    def _clean_env() -> dict[str, str]:
        """The server's environment minus anything that looks like a credential."""
        env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
        env.update(PYTHONDONTWRITEBYTECODE="1", CI="true",
                   # `python` in the test command resolves to the interpreter running AutoFixAI
                   PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
        return env

    def _sandbox_env(self) -> dict[str, str]:
        """A minimal environment built from scratch: nothing is inherited from the server."""
        return {
            "PATH": f"{self.env_dir / 'bin'}:/usr/local/bin:/usr/bin:/bin",
            "VIRTUAL_ENV": str(self.env_dir),
            "HOME": str(self.env_dir / "home"),
            "LANG": "C.UTF-8",
            "CI": "true",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
        }

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
        _chown_tree(self.root)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.env_dir, ignore_errors=True)
