"""Tests for BYONRuntimeClient and the DEMO client - fully mocked, no live BYON/Claude."""
from __future__ import annotations

import importlib

import pytest

pytest.importorskip("httpx")

brc = importlib.import_module("app.byon_runtime_client")


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeHTTP:
    """Minimal stand-in for an injected HTTP client: routes by (method, path)."""
    def __init__(self, handler):
        self._handler = handler

    def request(self, method, path, **kw):
        return self._handler(method, path, kw)


def _client(handler):
    return brc.BYONRuntimeClient("http://test", http_client=_FakeHTTP(handler))


def test_error_when_backend_unreachable():
    def handler(method, path, kw):
        raise ConnectionError("refused")
    r = _client(handler).chat("lucian", "s1", "hello")
    assert r.epistemic_status == "ERROR"
    assert r.grounded is False
    assert r.answer == "BYON runtime is not available."


def test_refused_when_final_audit_missing():
    def handler(method, path, kw):
        return _Resp(200, {"answer": "LEAK", "epistemic_status": "KNOWN",
                           "grounded": True, "final_audit_passed": False,
                           "audit_trace_id": "trace_x"})
    r = _client(handler).chat("lucian", "s1", "hi")
    assert r.epistemic_status == "REFUSED"
    assert r.grounded is False
    assert "final audit" in r.answer.lower()
    assert "LEAK" not in r.answer


def test_unknown_is_preserved():
    def handler(method, path, kw):
        return _Resp(200, {"answer": "", "epistemic_status": "UNKNOWN",
                           "grounded": False, "final_audit_passed": True,
                           "audit_trace_id": "trace_u"})
    r = _client(handler).chat("lucian", "s1", "oov")
    assert r.epistemic_status == "UNKNOWN"
    assert r.grounded is False and r.answer == ""


def test_refused_is_preserved():
    def handler(method, path, kw):
        return _Resp(200, {"answer": "no", "epistemic_status": "REFUSED",
                           "grounded": False, "final_audit_passed": True,
                           "audit_trace_id": "trace_r"})
    r = _client(handler).chat("lucian", "s1", "x")
    assert r.epistemic_status == "REFUSED" and r.grounded is False


def test_known_passthrough():
    def handler(method, path, kw):
        return _Resp(200, {"answer": "Level 2", "epistemic_status": "KNOWN",
                           "grounded": True, "final_audit_passed": True,
                           "audit_trace_id": "trace_k",
                           "grounding_summary": {"has_valid_memory": True}})
    r = _client(handler).chat("lucian", "s1", "level?")
    assert r.epistemic_status == "KNOWN" and r.grounded is True
    assert r.answer == "Level 2" and r.audit_trace_id == "trace_k"


def test_user_id_required():
    with pytest.raises(ValueError):
        _client(lambda *a: _Resp()).chat("", "s1", "hi")


def test_session_id_required():
    with pytest.raises(ValueError):
        _client(lambda *a: _Resp()).chat("lucian", "", "hi")


def test_http_error_status_becomes_error_not_fabrication():
    def handler(method, path, kw):
        return _Resp(503, {"detail": "BYON_KILL_SWITCH active"})
    r = _client(handler).chat("lucian", "s1", "hi")
    assert r.epistemic_status == "ERROR" and r.grounded is False


def test_forget_failure_does_not_crash():
    def handler(method, path, kw):
        if path == "/v1/forget":
            return _Resp(404, {"detail": "not found"})
        return _Resp(200, {})
    out = _client(handler).forget("lucian", "s1")
    assert out["ok"] is False and "not available" in out["message"].lower()


def test_audit_failure_does_not_crash():
    def handler(method, path, kw):
        return _Resp(404, {"detail": "no trace"})
    out = _client(handler).audit_trace("trace_missing")
    assert out["ok"] is False and "not available" in out["message"].lower()


def test_demo_mode_is_marked_demo():
    demo = brc.DemoBYONClient()
    assert demo.BANNER == "DEMO MODE - NOT REAL BYON RUNTIME"
    r = demo.chat("lucian", "s1", "what level?")
    assert r.raw.get("demo") is True
    pw = demo.chat("lucian", "s1", "what is my password?")
    assert pw.epistemic_status == "UNKNOWN" and pw.answer == ""
