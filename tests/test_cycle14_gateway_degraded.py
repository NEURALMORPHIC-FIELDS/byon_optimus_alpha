# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S6 - gateway degraded behavior when the memory-service is down.

When the canonical memory-service is unreachable the Gateway reports it, and chat/research return
ERROR with NO fabricated answer, NO Claude fallback that bypasses memory, and NO LocalBYONBackend
fallback in REAL. Tested at the backend level with an injected down memory client + a Claude probe
that records whether it was called.
"""
from __future__ import annotations

import importlib

msb = importlib.import_module("gateway.memory_service_backend")
hc = importlib.import_module("app.health_checks")


class DownMem:
    def health(self):
        return {"_reachable": False, "error": "connection refused"}

    def stats(self):
        raise AssertionError("stats() must not be called when memory-service is down")


class TrackingClaude:
    available = True

    def __init__(self):
        self.calls = 0

    def propose(self, *a, **k):
        self.calls += 1
        return {"hypothesis": "should-not-be-used"}


def _down_backend():
    claude = TrackingClaude()
    backend = msb.MemoryServiceBackend(mem_client=DownMem(), claude_provider=claude)
    return backend, claude


def test_gateway_health_reports_memory_service_down():
    backend, _ = _down_backend()
    st = backend.status()
    assert st["memory_service_up"] is False
    assert st["memory_service"]["reachable"] is False


def test_memory_status_reports_backend_down():
    backend, _ = _down_backend()
    ms = backend.memory_status(user_id="u", namespace_dir=None)
    assert ms["memory_service_up"] is False
    assert ms["available"] is False


def test_chat_returns_error_when_memory_service_down(tmp_path):
    backend, _ = _down_backend()
    res = backend.chat(user_id="u", session_id="s", channel="api", message="who won?",
                       namespace_dir=tmp_path)
    assert res.epistemic_status == "ERROR"
    assert res.answer == ""                          # no fabricated answer


def test_research_returns_error_when_memory_service_down(tmp_path):
    backend, _ = _down_backend()
    out = backend.research(user_id="u", session_id="s", question="who won?", namespace_dir=tmp_path)
    assert out["epistemic_status"] == "ERROR"
    assert out["memory_service_up"] is False
    assert out["answer"] == ""


def test_no_claude_fallback_when_memory_down(tmp_path):
    backend, claude = _down_backend()
    backend.chat(user_id="u", session_id="s", channel="api", message="capital of France?",
                 namespace_dir=tmp_path)
    backend.research(user_id="u", session_id="s", question="capital of France?", namespace_dir=tmp_path)
    assert claude.calls == 0                          # memory down => Claude is never consulted


def test_no_local_backend_fallback_in_real(tmp_path):
    # the REAL-mode backend stays MemoryServiceBackend and returns ERROR; it does NOT swap to a
    # LocalBYONBackend when memory is down
    backend, _ = _down_backend()
    assert backend.__class__.__name__ == "MemoryServiceBackend"
    out = backend.research(user_id="u", session_id="s", question="x?", namespace_dir=tmp_path)
    assert out["epistemic_status"] == "ERROR"
    assert backend.__class__.__name__ == "MemoryServiceBackend"   # no swap occurred


def test_ui_status_reports_memory_service_down(monkeypatch):
    # summarize() drives the UI health panel; when the backend reports memory down it must show DOWN
    fake_health = {"_reachable": True, "backend": {"backend": "memory-service",
                                                   "memory_service_up": False,
                                                   "memory_service": {"reachable": False},
                                                   "fcem": {"runtime_proven": False}}}
    monkeypatch.setattr(hc, "gateway_health", lambda url: fake_health)
    panel = hc.summarize("http://127.0.0.1:8090")
    assert panel["Gateway"] == "OK"
    assert panel["Memory/D_Cortex"] == "DOWN"
