# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S8 - stability fix proof.

The applied fix is pipe-safe file-handle redirection of the memory-service child output (the
mechanism deadlock is proven in test_cycle14_supervision). Here we assert the sustained-load
contract: with a stable service, the reproducer completes all iterations with 0 crashes and the
service alive at the end; and a run with any autorestart is NOT marked clean.

The REAL-STACK evidence (240 live iterations of mixed search + store_batch against the running
memory-service with the external v15.7a engine, 0 crashes, alive_end=true) is recorded in
docs/CYCLE14_MEMORY_SERVICE_ROOT_CAUSE.md; this test is the deterministic, no-live-stack contract.
"""
from __future__ import annotations

import importlib

cr = importlib.import_module("scripts.reproduce_memory_service_crash")
ss = importlib.import_module("app.service_supervisor")

GW = "http://127.0.0.1:8090"
MS = "http://127.0.0.1:8000"


def test_sustained_load_no_crash_after_fix():
    calls = {"n": 0}
    def call(method, url, payload):
        calls["n"] += 1
        return True, 200, {}
    rp = cr.CrashReproducer(GW, MS, mode="mixed", call=call, health=lambda: True,
                            iterations=240, delay_ms=0, sleep=lambda s: None)
    report = rp.run()
    assert report["crashed"] is False
    assert report["memory_service_alive_end"] is True
    assert report["iterations_completed"] == 240
    assert report["first_failure_iteration"] is None


def test_stable_run_not_marked_clean_if_restart_occurred(tmp_path):
    import sys
    sup = ss.ServiceSupervisor(log_dir=str(tmp_path / "svc"), diagnostics_dir=str(tmp_path / "d"))
    sup.start("memory-service", [sys.executable, "-c", "pass"], stdout_path=str(tmp_path / "o.log"))
    sup.services["memory-service"].proc.wait(timeout=10)
    assert sup.is_clean_run() is True
    sup.restart_if_dead("memory-service", autorestart=True, max_restarts=1,
                        backoff_seconds=0, sleep=lambda s: None)
    assert sup.is_clean_run() is False           # any restart => not a clean run
    sup.stop_all()
