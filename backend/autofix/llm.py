"""Thin wrapper around Nebius Token Factory's OpenAI-compatible API.

AutoFixAI routes work across three Nemotron tiers:
  nano  - fast, cheap calls: log triage, PR write-ups
  super - the default coding agent that edits files and runs tests
  ultra - escalation tier for failures Super could not fix
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from .config import settings

TIERS = ("nano", "super", "ultra")

# Fallback IDs used only when /v1/models cannot be listed.
_DEFAULT_IDS = {
    "nano": "nvidia/Nemotron-3-Nano-30B-A3B",
    "super": "nvidia/Nemotron-3-Super-120B-A12B",
    "ultra": "nvidia/Nemotron-3-Ultra-550B-A55B",
}

_resolved_cache: dict[str, str] | None = None

_THINK_RE =re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str | None) -> str:
    if not text:
        return ""
    text = _THINK_RE.sub("", text)
    # Some reasoning outputs only emit the closing tag.
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def _pick(ids: list[str], tier: str) -> str | None:
    """Choose the best Nemotron model ID for a tier from the provider's catalog."""
    candidates = [
        i for i in ids if "nemotron" in i.lower() and tier in i.lower()
    ]
    if not candidates:
        return None
    # Prefer generation-3 text models over omni / vision / embedding variants.
    def score(model_id: str) -> tuple[int, int, int]:
        low = model_id.lower()
        return (
            "nemotron-3" in low or "nemotron3" in low,
            not any(x in low for x in ("omni", "vl", "embed", "rerank", "safety", "reward")),
            -len(model_id),
        )

    return max(candidates, key=score)


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "seconds": round(self.seconds, 2),
        }


@dataclass
class LLM:
    client: OpenAI
    models: dict[str, str]
    usage: dict[str, Usage] = field(default_factory=lambda: {t: Usage() for t in TIERS})

    @classmethod
    def from_settings(cls) -> "LLM":
        if not settings.api_key:
            raise RuntimeError("NEBIUS_API_KEY is not set. Copy .env.example to .env and fill it in.")
        global _resolved_cache
        client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=180)
        if _resolved_cache is None:
            _resolved_cache = resolve_models(client)
        return cls(client=client, models=dict(_resolved_cache))

    def chat(
        self,
        tier: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
        thinking: bool | None = None,
    ):
        """Call one tier and return the raw assistant message.

        `thinking` toggles Nemotron's reasoning mode via the chat template; None keeps the model default.
        """
        kwargs: dict[str, Any] = {
            "model": self.models[tier],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if thinking is not None:
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": thinking}}

        started = time.monotonic()
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception:
            if not (json_mode or thinking is not None):
                raise
            # Not every deployment supports response_format / chat_template_kwargs; retry without them.
            kwargs.pop("response_format", None)
            kwargs.pop("extra_body", None)
            resp = self.client.chat.completions.create(**kwargs)

        u = self.usage[tier]
        u.calls += 1
        u.seconds += time.monotonic() - started
        if resp.usage:
            u.prompt_tokens += resp.usage.prompt_tokens or 0
            u.completion_tokens += resp.usage.completion_tokens or 0
        return resp.choices[0].message

    def chat_json(self, tier: str, messages: list[dict[str, Any]], **kw) -> dict[str, Any]:
        msg = self.chat(tier, messages, json_mode=True, **kw)
        return parse_json(strip_thinking(msg.content))

    def usage_report(self) -> dict[str, Any]:
        return {t: {"model": self.models[t], **self.usage[t].as_dict()} for t in TIERS}


def parse_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences and surrounding prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1], strict=False)
        raise


def resolve_models(client: OpenAI) -> dict[str, str]:
    overrides = {
        "nano": settings.model_nano,
        "super": settings.model_super,
        "ultra": settings.model_ultra,
    }
    try:
        available = [m.id for m in client.models.list().data]
    except Exception:
        available = []

    resolved: dict[str, str] = {}
    for tier in TIERS:
        resolved[tier] = overrides[tier] or _pick(available, tier) or _DEFAULT_IDS[tier]
    # If the catalog has no Ultra, fall back to Super so escalation still works.
    if not overrides["ultra"] and available and not _pick(available, "ultra"):
        resolved["ultra"] = resolved["super"]
    return resolved
