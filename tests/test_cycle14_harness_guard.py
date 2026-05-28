# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S3 - live-harness service-health guard tests (guard logic, no live stack)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("httpx")

_HARNESS = Path(__file__).resolve().parents[1] / "scripts" / "live_byon_eval.py"


def _load():
    spec = importlib.util.spec_from_file_location("live_byon_eval", _HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _guard(probe):
    m = _load()
    return m, m.ServiceHealthGuard("http://127.0.0.1:8090", "http://127.0.0.1:8000", health_probe=probe)


def test_live_harness_detects_memory_service_crash():
    m, g = _guard(lambda: False)               # memory-service is down
    g.after_gate("gate_1")
    assert g.crashed is True
    assert g.report_fields()["failure_category"] == m.CAT_MEMORY_SERVICE_CRASH


def test_live_harness_stops_on_memory_service_crash():
    state = {"alive": True}
    _, g = _guard(lambda: state["alive"])
    g.after_gate("gate_1")
    assert g.should_stop() is False
    state["alive"] = False
    g.after_gate("gate_2")
    assert g.should_stop() is True             # crash -> harness must stop


def test_live_harness_does_not_continue_after_service_crash():
    _, g = _guard(lambda: False)
    g.after_gate("gate_1")                     # crash detected
    # once crashed, before_gate refuses further gates
    assert g.before_gate("gate_2") is False
    assert g.before_gate("gate_3") is False


def test_gateway_up_memory_down_is_failure():
    # gateway up but memory down: precheck (memory-only probe) must FAIL, not pass
    _, g = _guard(lambda: False)
    pre = g.precheck()
    assert pre["healthy"] is False
    assert pre["failure_category"] == "MEMORY_SERVICE_CRASH"


def test_crash_report_includes_last_successful_gate():
    state = {"n": 0}
    def probe():
        state["n"] += 1
        return state["n"] < 3                  # alive for first 2 polls, then down
    _, g = _guard(probe)
    g.after_gate("gate_A")
    g.after_gate("gate_B")
    g.after_gate("gate_C")                     # this poll sees it down
    fields = g.report_fields()
    assert fields["last_successful_gate"] == "gate_B"
    assert fields["crash_detected_at_gate"] == "gate_C"
    assert fields["memory_service_crashed"] is True
    assert isinstance(fields["memory_service_health_trace"], list) and fields["memory_service_health_trace"]
