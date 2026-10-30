"""Runtime configuration, read once from the environment (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:  # python-dotenv is optional
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Nebius Token Factory (OpenAI-compatible)
    api_key: str = field(default_factory=lambda: os.environ.get("NEBIUS_API_KEY", ""), repr=False)
    base_url: str = field(
        default_factory=lambda: os.environ.get(
            "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"
        )
    )

    # Model tiers. Empty means "auto-resolve from /v1/models at startup".
    model_nano: str = field(default_factory=lambda: os.environ.get("AUTOFIX_MODEL_NANO", ""))
    model_super: str = field(default_factory=lambda: os.environ.get("AUTOFIX_MODEL_SUPER", ""))
    model_ultra: str = field(default_factory=lambda: os.environ.get("AUTOFIX_MODEL_ULTRA", ""))

    # Agent budget
    max_attempts: int = field(default_factory=lambda: _int("AUTOFIX_MAX_ATTEMPTS", 4))
    max_steps_per_attempt: int = field(default_factory=lambda: _int("AUTOFIX_MAX_STEPS", 14))
    escalate_after: int = field(default_factory=lambda: _int("AUTOFIX_ESCALATE_AFTER", 2))
    test_timeout_s: int = field(default_factory=lambda: _int("AUTOFIX_TEST_TIMEOUT", 180))
    setup_timeout_s: int = field(default_factory=lambda: _int("AUTOFIX_SETUP_TIMEOUT", 600))

    # Optional integrations
    github_token: str = field(default_factory=lambda: os.environ.get("GITHUB_TOKEN", ""), repr=False)
    github_webhook_secret: str = field(
        default_factory=lambda: os.environ.get("GITHUB_WEBHOOK_SECRET", ""), repr=False
    )
    tavily_api_key: str = field(default_factory=lambda: os.environ.get("TAVILY_API_KEY", ""), repr=False)

    # Where run workspaces are created
    work_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("AUTOFIX_WORK_DIR", Path.cwd() / ".autofix-runs")
        ).resolve()
    )


settings = Settings()
