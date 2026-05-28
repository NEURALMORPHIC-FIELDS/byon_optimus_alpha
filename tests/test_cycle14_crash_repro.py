# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S4 - crash reproduction tests (no live stack; HTTP + health injected)."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

cr = importlib.import_module("scripts.reproduce_memory_service_crash")

GW = "http://127.0.0.1:8090"
MS = "http://127.0.0.1:8000"


def ok_call(method, url, payload):
    return True, 200, {}


def healthy():
    return True


def dies_after(n):
    state = {"calls": 0}
    def health():
        state["calls"] += 1
        return state["calls"] <= n            # service dies after n health checks
    return health


def test_crash_repro_script_exists():
    assert Path("scripts/reproduce_memory_service_crash.py").exists()
    assert hasattr(cr, "CrashReproducer")


def test_crash_repro_writes_report(tmp_path):
    rp = cr.CrashReproducer(GW, MS, mode="mixed", call=ok_call, health=healthy,
                            iterations=3, delay_ms=0, sleep=lambda s: None)
    report = rp.run()
    jp, mp = rp.write_reports(report, diag_dir=tmp_path)
    assert jp.exists() and mp.exists()
    loaded = json.loads(jp.read_text(encoding="utf-8"))
    assert loaded["mode"] == "mixed"
    assert "crash reproduction" in mp.read_text(encoding="utf-8").lower()


def test_crash_repro_detects_down_service():
    rp = cr.CrashReproducer(GW, MS, mode="mixed", call=ok_call, health=dies_after(2),
                            iterations=10, delay_ms=0, stop_on_failure=True, sleep=lambda s: None)
    report = rp.run()
    assert report["crashed"] is True
    assert report["first_failure_iteration"] is not None


def test_crash_repro_records_endpoint_at_failure():
    rp = cr.CrashReproducer(GW, MS, mode="mixed", call=ok_call, health=dies_after(1),
                            iterations=10, delay_ms=0, stop_on_failure=True, sleep=lambda s: None)
    report = rp.run()
    assert report["endpoint_at_failure"] is not None
    assert report["suspected_trigger"] and "memory-service died" in report["suspected_trigger"]


def test_crash_repro_can_run_mixed_mode():
    rp = cr.CrashReproducer(GW, MS, mode="mixed", call=ok_call, health=healthy,
                            iterations=5, delay_ms=0, sleep=lambda s: None)
    report = rp.run()
    assert report["mode"] == "mixed"
    assert report["crashed"] is False
    assert report["iterations_completed"] == 5


def test_crash_repro_can_run_acquisition_store_mode():
    seen = []
    def rec_call(method, url, payload):
        seen.append((url, payload.get("action")))
        return True, 200, {}
    rp = cr.CrashReproducer(GW, MS, mode="acquisition-store", call=rec_call, health=healthy,
                            iterations=3, delay_ms=0, sleep=lambda s: None)
    report = rp.run()
    assert report["mode"] == "acquisition-store"
    # exercises store_batch (batched writes) on the CURRENT 13.3 surface
    assert any(action == "store_batch" for _, action in seen)
    assert any("/v1/research" in url for url, _ in seen)
