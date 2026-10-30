"""Tests for the public-deployment protections: input validation, rate limits, secret-free command env."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from autofix import hosted  # noqa: E402
from autofix.workspace import Workspace  # noqa: E402


def fake_github(status=200, private=False, size_kb=1000):
    def get(url, **kw):
        return SimpleNamespace(status_code=status, json=lambda: {"private": private, "size": size_kb})
    return get


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(hosted.httpx, "get", fake_github())


@pytest.mark.parametrize("url", [
    "/etc/passwd", "C:\\Users\\x", "file:///etc", "git@github.com:a/b.git", "http://github.com/a/b",
    "https://gitlab.com/a/b", "https://github.com/a", "https://github.com/a/b/tree/main",
    "https://github.com.evil.com/a/b", "https://github.com/a/b;rm -rf /",
])
def test_rejects_anything_but_public_github_https(url):
    with pytest.raises(hosted.Rejected):
        hosted.validate(url, None, "pytest", None, None)


def test_accepts_and_normalises_github_url():
    r = hosted.validate("https://github.com/Owner/my.repo.git/", "feature/x-1", " python -m pytest -q ", None, None)
    assert r.url == "https://github.com/Owner/my.repo" and r.ref == "feature/x-1"
    assert r.test_command == "python -m pytest -q" and r.setup_command is None


@pytest.mark.parametrize("ref", ["--upload-pack=x", "a..b", "a b", "x" * 101])
def test_rejects_bad_refs(ref):
    with pytest.raises(hosted.Rejected):
        hosted.validate("https://github.com/a/b", ref, "pytest", None, None)


def test_rejects_multiline_or_long_commands():
    with pytest.raises(hosted.Rejected):
        hosted.validate("https://github.com/a/b", None, "pytest\ncurl x", None, None)
    with pytest.raises(hosted.Rejected):
        hosted.validate("https://github.com/a/b", None, "pytest", "x" * 301, None)


def test_rejects_private_missing_and_large_repos(monkeypatch):
    for gh in (fake_github(status=404), fake_github(private=True), fake_github(size_kb=200 * 1024)):
        monkeypatch.setattr(hosted.httpx, "get", gh)
        with pytest.raises(hosted.Rejected):
            hosted.validate("https://github.com/a/b", None, "pytest", None, None)


def test_rate_limits(monkeypatch):
    monkeypatch.setattr(hosted, "RUNS_PER_IP_PER_HOUR", 2)
    monkeypatch.setattr(hosted, "USER_REPO_RUNS_PER_DAY", 3)
    lim = hosted.RateLimiter()
    lim.check("1.1.1.1", user_repo=False)
    lim.check("1.1.1.1", user_repo=True)
    with pytest.raises(hosted.Rejected) as e:
        lim.check("1.1.1.1", user_repo=False)
    assert e.value.status == 429
    lim.check("2.2.2.2", user_repo=True)
    lim.check("3.3.3.3", user_repo=True)
    with pytest.raises(hosted.Rejected):           # global daily cap for visitor repos
        lim.check("4.4.4.4", user_repo=True)
    lim.check("4.4.4.4", user_repo=False)           # demos still allowed


def test_client_ip_prefers_forwarded_header():
    assert hosted.client_ip({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, "10.0.0.1") == "9.9.9.9"
    assert hosted.client_ip({}, "10.0.0.1") == "10.0.0.1"


def test_commands_never_see_secrets(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "secret-1")
    monkeypatch.setenv("TAVILY_API_KEY", "secret-2")
    monkeypatch.setenv("GITHUB_TOKEN", "secret-3")
    env = Workspace._clean_env()
    assert not any(v.startswith("secret-") for v in env.values())
    sandbox = Workspace(ROOT, "true")._sandbox_env()
    assert set(sandbox) <= {"PATH", "VIRTUAL_ENV", "HOME", "LANG", "CI", "PYTHONDONTWRITEBYTECODE",
                            "PIP_DISABLE_PIP_VERSION_CHECK", "PIP_NO_INPUT"}
