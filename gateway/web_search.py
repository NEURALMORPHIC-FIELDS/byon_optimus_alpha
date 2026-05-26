"""Web search — the one genuinely-missing epistemic source (BYON has no web layer).

Pluggable provider, disabled by default. Web results are EVIDENCE CANDIDATES, never
auto-committed truth. Providers: disabled | duckduckgo | tavily | brave | serpapi | custom.
A custom callable can be injected (used by tests). If no provider/key is configured the
UI shows 'Web search not configured.'
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, List, Optional
from urllib.parse import urlparse


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str
    source_domain: str = ""
    retrieved_at: str = ""
    rank: int = 0
    claim: Optional[str] = None  # optional extracted assertion (set by structured providers/tests)

    def to_dict(self) -> dict:
        return asdict(self)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


class WebSearchProvider:
    name = "base"
    available = False

    def search(self, query: str, max_results: int = 5) -> List[WebResult]:
        raise NotImplementedError


class DisabledWebSearch(WebSearchProvider):
    name = "disabled"
    available = False

    def search(self, query: str, max_results: int = 5) -> List[WebResult]:
        return []


class CallableWebSearch(WebSearchProvider):
    """Wraps an injected callable `fn(query, max_results) -> list[WebResult|dict]`. Used by
    tests and for a `custom` provider."""
    name = "custom"

    def __init__(self, fn: Callable[[str, int], List[Any]]) -> None:
        self._fn = fn
        self.available = True

    def search(self, query: str, max_results: int = 5) -> List[WebResult]:
        out: List[WebResult] = []
        for i, r in enumerate(self._fn(query, max_results) or []):
            if isinstance(r, WebResult):
                out.append(r)
            elif isinstance(r, dict):
                out.append(WebResult(
                    title=r.get("title", ""), url=r.get("url", ""), snippet=r.get("snippet", ""),
                    source_domain=r.get("source_domain") or _domain(r.get("url", "")),
                    retrieved_at=r.get("retrieved_at", ""), rank=r.get("rank", i),
                    claim=r.get("claim")))
        return out


class DuckDuckGoWebSearch(WebSearchProvider):
    """Best-effort, keyless. Uses the `ddgs`/`duckduckgo_search` package if installed."""
    name = "duckduckgo"

    def __init__(self) -> None:
        self.available = False
        self._impl = None
        for mod, attr in (("ddgs", "DDGS"), ("duckduckgo_search", "DDGS")):
            try:
                m = __import__(mod, fromlist=[attr])
                self._impl = getattr(m, attr)
                self.available = True
                break
            except Exception:
                continue

    def search(self, query: str, max_results: int = 5) -> List[WebResult]:
        if not self._impl:
            return []
        import time
        out: List[WebResult] = []
        try:
            with self._impl() as ddgs:
                for i, r in enumerate(ddgs.text(query, max_results=max_results)):
                    url = r.get("href") or r.get("url", "")
                    out.append(WebResult(
                        title=r.get("title", ""), url=url, snippet=r.get("body", ""),
                        source_domain=_domain(url),
                        retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), rank=i))
        except Exception:
            return []
        return out


class HttpKeyedWebSearch(WebSearchProvider):
    """Tavily / Brave / SerpAPI via httpx. Requires the provider's API key in env.
    Kept minimal; returns [] (and available=False) if no key is configured."""
    def __init__(self, name: str, api_key: str) -> None:
        self.name = name
        self.available = bool(api_key)
        self._key = api_key

    def search(self, query: str, max_results: int = 5) -> List[WebResult]:
        if not self.available:
            return []
        import time
        import httpx
        try:
            if self.name == "tavily":
                r = httpx.post("https://api.tavily.com/search",
                               json={"api_key": self._key, "query": query, "max_results": max_results},
                               timeout=20.0).json()
                items = r.get("results", [])
                return [WebResult(title=it.get("title", ""), url=it.get("url", ""),
                                  snippet=it.get("content", ""), source_domain=_domain(it.get("url", "")),
                                  retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), rank=i)
                        for i, it in enumerate(items)]
            if self.name == "brave":
                r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                              headers={"X-Subscription-Token": self._key},
                              params={"q": query, "count": max_results}, timeout=20.0).json()
                items = (r.get("web", {}) or {}).get("results", [])
                return [WebResult(title=it.get("title", ""), url=it.get("url", ""),
                                  snippet=it.get("description", ""), source_domain=_domain(it.get("url", "")),
                                  retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), rank=i)
                        for i, it in enumerate(items)]
            if self.name == "serpapi":
                r = httpx.get("https://serpapi.com/search",
                              params={"api_key": self._key, "q": query, "num": max_results}, timeout=20.0).json()
                items = r.get("organic_results", [])
                return [WebResult(title=it.get("title", ""), url=it.get("link", ""),
                                  snippet=it.get("snippet", ""), source_domain=_domain(it.get("link", "")),
                                  retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), rank=i)
                        for i, it in enumerate(items)]
        except Exception:
            return []
        return []


def get_provider(injected: Optional[WebSearchProvider] = None) -> WebSearchProvider:
    """Resolve the provider from env. BYON_WEB_SEARCH_ENABLED gates everything."""
    if injected is not None:
        return injected
    if os.environ.get("BYON_WEB_SEARCH_ENABLED", "false").strip().lower() not in ("1", "true", "yes", "on"):
        return DisabledWebSearch()
    provider = os.environ.get("BYON_WEB_SEARCH_PROVIDER", "duckduckgo").strip().lower()
    if provider == "duckduckgo":
        return DuckDuckGoWebSearch()
    if provider in ("tavily", "brave", "serpapi"):
        key = os.environ.get(f"{provider.upper()}_API_KEY", "").strip()
        return HttpKeyedWebSearch(provider, key)
    return DisabledWebSearch()
