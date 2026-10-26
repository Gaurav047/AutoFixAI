"""Web research with Tavily.

Two entry points feed the same per-run collector:
  - the research step after triage, for failures caused by a library, language version or API change
  - the `web_search` tool, which the coding agent can call on its own

Every source Tavily returns is recorded, so the PR can cite exactly what was retrieved.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

from .config import settings

TAVILY_URL = "https://api.tavily.com/search"

# Triage categories where the fix often depends on facts outside the repository.
RESEARCH_CATEGORIES = {"import_error", "dependency", "api_change", "config"}


def enabled() -> bool:
    return bool(settings.tavily_api_key)


def tavily_search(query: str, max_results: int = 5) -> dict[str, Any]:
    resp = httpx.post(
        TAVILY_URL,
        headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
        json={"query": query, "max_results": max_results, "include_answer": True,
              "search_depth": "advanced", "topic": "general"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


class Research:
    """Runs Tavily searches for one fix run and remembers what was found."""

    def __init__(self, emit: Callable[[str, dict[str, Any]], None]):
        self.emit = emit
        self.searches = 0
        self.sources: dict[str, str] = {}   # url -> title, in the order first seen
        self.findings: list[dict[str, Any]] = []

    def search(self, query: str, origin: str) -> dict[str, Any]:
        self.searches += 1
        try:
            data = tavily_search(query)
        except Exception as e:
            self.emit("research", {"origin": origin, "query": query, "error": str(e), "sources": []})
            return {"query": query, "error": str(e), "results": []}

        results = [
            {"title": r.get("title") or r.get("url"), "url": r.get("url"),
             "snippet": (r.get("content") or "").strip()[:500]}
            for r in data.get("results", []) if r.get("url")
        ]
        for r in results:
            self.sources.setdefault(r["url"], r["title"])
        finding = {"origin": origin, "query": query, "answer": (data.get("answer") or "").strip(),
                   "sources": results}
        self.findings.append(finding)
        self.emit("research", finding)
        return finding

    @staticmethod
    def as_text(finding: dict[str, Any]) -> str:
        if finding.get("error"):
            return f"Web search failed: {finding['error']}"
        parts = []
        if finding.get("answer"):
            parts.append(f"Summary: {finding['answer']}")
        for s in finding.get("sources", []):
            parts.append(f"- {s['title']} ({s['url']})\n  {s['snippet']}")
        return "\n".join(parts) or "No results."

    def references_md(self) -> str:
        if not self.sources:
            return ""
        lines = [f"- [{title}]({url})" for url, title in self.sources.items()]
        return "## References\nSources retrieved with Tavily web search during this fix:\n" + "\n".join(lines)

    def report(self) -> dict[str, Any]:
        return {"searches": self.searches, "sources": [{"url": u, "title": t} for u, t in self.sources.items()]}
