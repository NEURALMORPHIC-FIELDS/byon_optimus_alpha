# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S1 - pre-flight live-stack health check tests (no live stack; HTTP is injected)."""
from __future__ import annotations

import importlib
import json

cs = importlib.import_module("scripts.check_live_stack")

GW = "http://127.0.0.1:8090"
MS = "http://127.0.0.1:8000"


def make_getter(*, gateway_ok=True, memory_ok=True, relation_5xx=False, lifeloop_5xx=False):
    def get(url):
        if url.endswith("/v1/health"):
            return (True, 200, {"status": "ok"}) if gateway_ok else (False, 0, {"error": "refused"})
        if url.endswith(":8000/health") or url.endswith("/health"):
            return (True, 200, {"status": "ok"}) if memory_ok else (False, 0, {"error": "refused"})
        if "relation-field/status" in url:
            return (True, 500 if relation_5xx else 200, {})
        if url.endswith("/v1/lifeloop"):
            return (True, 500 if lifeloop_5xx else 200, {})
        return (True, 200, {})
    return get


def test_stack_check_detects_gateway_down():
    r = cs.check_stack(GW, MS, get_json=make_getter(gateway_ok=False))
    assert r["healthy"] is False
    assert r["exit_code"] == cs.EXIT_GATEWAY_DOWN


def test_stack_check_detects_memory_service_down():
    r = cs.check_stack(GW, MS, get_json=make_getter(memory_ok=False))
    assert r["healthy"] is False
    assert r["exit_code"] == cs.EXIT_MEMORY_DOWN


def test_gateway_up_memory_down_is_not_healthy():
    r = cs.check_stack(GW, MS, get_json=make_getter(gateway_ok=True, memory_ok=False))
    assert r["checks"]["gateway"]["ok"] is True
    assert r["checks"]["memory_service"]["ok"] is False
    assert r["healthy"] is False                      # gateway-up-memory-down is NOT healthy


def test_stack_check_detects_writer_lock_active():
    r = cs.check_stack(GW, MS, get_json=make_getter(), writer_lock_active=lambda: True)
    assert r["exit_code"] == cs.EXIT_WRITER_LOCK
    assert r["checks"]["writer_lock"]["active"] is True


def test_stack_check_writes_json_and_md(tmp_path):
    r = cs.check_stack(GW, MS, get_json=make_getter())
    jp, mp = cs.write_reports(r, diag_dir=tmp_path)
    assert jp.exists() and mp.exists()
    loaded = json.loads(jp.read_text(encoding="utf-8"))
    assert loaded["exit_code"] == r["exit_code"]
    assert "Live stack health" in mp.read_text(encoding="utf-8")


def test_healthy_when_all_up():
    r = cs.check_stack(GW, MS, get_json=make_getter(), writer_lock_active=lambda: False)
    assert r["healthy"] is True and r["exit_code"] == cs.EXIT_HEALTHY


def test_relation_endpoint_5xx_is_endpoint_error():
    r = cs.check_stack(GW, MS, get_json=make_getter(relation_5xx=True), writer_lock_active=lambda: False)
    assert r["exit_code"] == cs.EXIT_ENDPOINT_ERROR
