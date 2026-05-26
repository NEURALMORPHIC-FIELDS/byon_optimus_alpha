"""Tests for the web search provider layer."""
from __future__ import annotations

import importlib

ws = importlib.import_module("gateway.web_search")


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("BYON_WEB_SEARCH_ENABLED", raising=False)
    p = ws.get_provider()
    assert p.name == "disabled" and p.available is False
    assert p.search("anything") == []


def test_injected_provider_is_used():
    custom = ws.CallableWebSearch(lambda q, n: [{"title": "t", "url": "https://x.com/a", "snippet": "s"}])
    assert ws.get_provider(custom) is custom


def test_callable_wraps_dicts_into_webresults():
    prov = ws.CallableWebSearch(lambda q, n: [
        {"title": "France 1998", "url": "https://fifa.com/1998", "snippet": "France won", "claim": "France"}])
    res = prov.search("1998 world cup", 5)
    assert prov.available is True and len(res) == 1
    r = res[0]
    assert isinstance(r, ws.WebResult)
    assert r.source_domain == "fifa.com" and r.claim == "France"


def test_keyed_provider_unavailable_without_key(monkeypatch):
    monkeypatch.setenv("BYON_WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("BYON_WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    p = ws.get_provider()
    assert p.name == "tavily" and p.available is False  # UI shows "not configured"
