"""Tests for the BYON Alpha App wiring: log store, runtime manager, demo labelling,
and end-to-end UI-log writes - all without live BYON or Claude."""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("httpx")

us = importlib.import_module("app.user_store")
rm = importlib.import_module("app.runtime_manager")
lc = importlib.import_module("app.local_config")
brc = importlib.import_module("app.byon_runtime_client")


def test_ui_log_writes_jsonl(tmp_path):
    store = us.UILogStore(tmp_path / "logs")
    p = store.append(user_id="lucian", session_id="s1", message="hi",
                     response="Level 2", epistemic_status="KNOWN",
                     grounded=True, audit_trace_id="trace_k")
    assert p.exists()
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["epistemic_status"] == "KNOWN"
    assert rows[-1]["user_id"] == "lucian" and rows[-1]["audit_trace_id"] == "trace_k"


def test_ui_log_never_contains_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SHOULD-NOT-APPEAR")
    store = us.UILogStore(tmp_path / "logs")
    p = store.append(user_id="u", session_id="s", message="hi", response="ok",
                     epistemic_status="KNOWN", grounded=True, audit_trace_id="t")
    assert "SHOULD-NOT-APPEAR" not in p.read_text(encoding="utf-8")


def test_demo_mode_runtime_is_marked(monkeypatch):
    monkeypatch.setenv("BYON_ALPHA_DEMO_MODE", "true")
    cfg = lc.AlphaConfig.from_env()
    status = rm.build_runtime(cfg)
    assert status.mode == "DEMO"
    launch, message = rm.should_launch(cfg, status)
    assert launch is True
    assert "DEMO MODE - NOT REAL BYON RUNTIME" in message


def test_real_mode_refuses_launch_when_gateway_down(monkeypatch):
    monkeypatch.setenv("BYON_ALPHA_DEMO_MODE", "false")
    monkeypatch.setenv("BYON_ALPHA_ALLOW_ERROR_UI", "false")
    # Point at a port nothing is listening on → unreachable.
    monkeypatch.setenv("BYON_GATEWAY_URL", "http://127.0.0.1:59999")
    cfg = lc.AlphaConfig.from_env()
    status = rm.build_runtime(cfg)
    assert status.mode == "REAL" and status.gateway_reachable is False
    launch, message = rm.should_launch(cfg, status)
    assert launch is False
    assert "not reachable" in message.lower()


def test_real_mode_error_ui_opt_in(monkeypatch):
    monkeypatch.setenv("BYON_ALPHA_DEMO_MODE", "false")
    monkeypatch.setenv("BYON_ALPHA_ALLOW_ERROR_UI", "true")
    monkeypatch.setenv("BYON_GATEWAY_URL", "http://127.0.0.1:59999")
    cfg = lc.AlphaConfig.from_env()
    status = rm.build_runtime(cfg)
    launch, _ = rm.should_launch(cfg, status)
    assert launch is True  # allowed to show error-only UI


def test_end_to_end_chat_logs_via_demo_client(tmp_path, monkeypatch):
    """The app flow: demo client → response → UI log. No live BYON."""
    store = us.UILogStore(tmp_path / "logs")
    demo = brc.DemoBYONClient()
    resp = demo.chat("lucian", "s1", "what level can BYON claim?")
    store.append(user_id="lucian", session_id="s1", message="what level?",
                 response=resp.answer, epistemic_status=resp.epistemic_status,
                 grounded=resp.grounded, audit_trace_id=resp.audit_trace_id)
    p = store.path_for("lucian", "s1")
    assert p.exists() and resp.epistemic_status in ("KNOWN", "UNKNOWN")


def test_run_alpha_app_importable():
    mod = importlib.import_module("run_alpha_app")
    assert hasattr(mod, "main")
