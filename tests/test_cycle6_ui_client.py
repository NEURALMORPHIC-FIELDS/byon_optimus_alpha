"""Cycle 6 target 7 - UI/Gateway client for the Life State panel.

All LifeLoop UI actions go through the Gateway client (never memory-service directly), so we
assert the client hits the /v1/lifeloop* Gateway paths.
"""
from __future__ import annotations

import importlib

import pytest

pytest.importorskip("httpx")

brc = importlib.import_module("app.byon_runtime_client")


class _Resp:
    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self._p = payload or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _RecordingHTTP:
    def __init__(self):
        self.calls = []

    def request(self, method, path, **kw):
        self.calls.append((method, path))
        if path == "/v1/lifeloop":
            return _Resp({"lifeloop": {"enabled": True, "version": "v2", "pressure_total": 1.5,
                                       "pending_research_tasks": [{"task_id": "rt_1"}]}})
        return _Resp({"ok": True})


def _client():
    http = _RecordingHTTP()
    return brc.BYONRuntimeClient("http://gateway", http_client=http), http


def test_ui_client_exposes_lifeloop_state():
    c, http = _client()
    data = c.lifeloop_state()
    assert data["lifeloop"]["version"] == "v2" and data["lifeloop"]["pressure_total"] == 1.5
    assert ("GET", "/v1/lifeloop") in http.calls


def test_ui_action_calls_gateway_endpoint():
    c, http = _client()
    c.lifeloop_tick()
    c.lifeloop_run_task("rt_1")
    c.lifeloop_approve_web("rt_1")
    c.lifeloop_cancel_task("rt_1")
    paths = [p for _, p in http.calls]
    assert "/v1/lifeloop/tick" in paths
    assert "/v1/lifeloop/run-task/rt_1" in paths
    assert "/v1/lifeloop/approve-web/rt_1" in paths
    assert "/v1/lifeloop/cancel-task/rt_1" in paths


def test_ui_does_not_call_memory_service_directly():
    c, http = _client()
    c.lifeloop_state(); c.lifeloop_tick(); c.lifeloop_run_task("x")
    for _, path in http.calls:
        assert path.startswith("/v1/")           # only the Gateway surface, never :8000 / memory-service
        assert "memory-service" not in path and ":8000" not in path


def test_demo_client_lifeloop_is_safe():
    d = brc.DemoBYONClient()
    st = d.lifeloop_state()["lifeloop"]
    assert st["version"] == "v2" and st["enabled"] is True
    assert d.lifeloop_tick()["demo"] is True


def test_ui_builds_with_life_panel():
    import inspect
    import app.alpha_ui as ui
    src = inspect.getsource(ui.build_ui)
    for token in ["Life State", "refresh_life", "tick_btn", "run_task_btn",
                  "approve_web_btn", "cancel_task_btn", "lifeloop_state",
                  "mark_resolved_btn", "evidence_btn"]:
        assert token in src, f"UI missing {token}"


def test_ui_client_mark_resolved_and_evidence_call_gateway():
    c, http = _client()
    c.lifeloop_mark_resolved("some topic")
    c.lifeloop_task_evidence("rt_1")
    paths = [p for _, p in http.calls]
    assert "/v1/lifeloop/mark-resolved" in paths
    assert "/v1/lifeloop/task/rt_1" in paths
    for _, p in http.calls:
        assert p.startswith("/v1/")          # gateway only, never memory-service


def test_ui_client_candidate_ops_call_gateway():
    c, http = _client()
    c.lifeloop_candidates()
    c.lifeloop_candidate("cand_1")
    c.lifeloop_candidate_op("cand_1", "mark-false")
    c.lifeloop_candidate_op("cand_1", "approve-commit")
    paths = [p for _, p in http.calls]
    assert "/v1/lifeloop/candidates" in paths
    assert "/v1/lifeloop/candidate/cand_1" in paths
    assert "/v1/lifeloop/candidate/cand_1/mark-false" in paths
    assert "/v1/lifeloop/candidate/cand_1/approve-commit" in paths
    for _, p in http.calls:
        assert p.startswith("/v1/") and "memory-service" not in p


def test_ui_builds_with_candidate_panel():
    import inspect
    import app.alpha_ui as ui
    src = inspect.getsource(ui.build_ui)
    for token in ["Candidate lifecycle", "refresh_cand_btn", "mark_false_btn",
                  "approve_commit_btn", "archive_cand_btn", "lifeloop_candidates"]:
        assert token in src, f"UI missing candidate token {token}"
