# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S2 - memory-service crash monitor tests (no live stack; HTTP + sampler injected)."""
from __future__ import annotations

import importlib
import itertools
import json

mm = importlib.import_module("scripts.monitor_memory_service")

GW = "http://127.0.0.1:8090"
MS = "http://127.0.0.1:8000"


def getter(*, memory_alive=True, gateway_alive=True):
    def get(url):
        if "/v1/health" in url:
            return (gateway_alive, 200 if gateway_alive else 0, {})
        if url.endswith("/health"):
            return (memory_alive, 200 if memory_alive else 0, {})
        return (True, 200, {})
    return get


def rising_sampler():
    counter = itertools.count(0)
    def sample():
        i = next(counter)
        return {"timestamp": f"t{i}", "available": True, "rss_mb": 100.0 + 10.0 * i,
                "cpu_percent": 5.0, "num_fds": 30 + i}
    return sample


def test_monitor_detects_service_down():
    mon = mm.MemoryServiceMonitor(GW, MS, get_json=getter(memory_alive=False),
                                  resource_sampler=lambda: {"available": False})
    rep = mon.run(samples=2, interval=0, sleep=lambda s: None)
    assert rep["memory_service_crashed"] is True
    assert rep["memory_alive_at_last_poll"] is False


def test_monitor_records_first_failure():
    mon = mm.MemoryServiceMonitor(GW, MS, get_json=getter(memory_alive=False),
                                  resource_sampler=lambda: {"available": False})
    mon.run(samples=1, interval=0, sleep=lambda s: None)
    assert mon.first_failure_timestamp is not None


def test_monitor_records_gateway_alive_memory_dead():
    mon = mm.MemoryServiceMonitor(GW, MS, get_json=getter(memory_alive=False, gateway_alive=True),
                                  resource_sampler=lambda: {"available": False})
    rep = mon.run(samples=1, interval=0, sleep=lambda s: None)
    assert rep["gateway_alive_at_last_poll"] is True
    assert rep["memory_alive_at_last_poll"] is False


def test_monitor_does_not_mark_gateway_health_as_memory_health():
    # gateway UP, memory DOWN -> memory must be reported DOWN (not inferred from gateway)
    mon = mm.MemoryServiceMonitor(GW, MS, get_json=getter(memory_alive=False, gateway_alive=True),
                                  resource_sampler=lambda: {"available": False})
    e = mon.poll_once()
    assert e["gateway_alive"] is True
    assert e["memory_service_alive"] is False


def test_monitor_records_resource_timeseries():
    mon = mm.MemoryServiceMonitor(GW, MS, get_json=getter(), resource_sampler=rising_sampler())
    rep = mon.run(samples=4, interval=0, sleep=lambda s: None)
    ts = rep["resource_timeseries"]
    assert len(ts) == 4
    assert all("rss_mb" in s for s in ts)
    trend = rep["resource_trend"]
    assert trend["samples"] == 4
    assert trend["rss_rising"] is True                 # rising trend distinguishes a leak
    assert trend["rss_mb_delta"] > 0


def test_monitor_writes_json_and_md(tmp_path):
    mon = mm.MemoryServiceMonitor(GW, MS, get_json=getter(), resource_sampler=rising_sampler())
    mon.run(samples=3, interval=0, sleep=lambda s: None)
    jp, mp = mon.write_reports(diag_dir=tmp_path)
    assert jp.exists() and mp.exists()
    loaded = json.loads(jp.read_text(encoding="utf-8"))
    assert "resource_trend" in loaded
    assert "Resource trend (time series)" in mp.read_text(encoding="utf-8")
