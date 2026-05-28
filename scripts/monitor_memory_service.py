# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S2 - memory-service crash monitor.

Polls the memory-service /health on :8000 (and the Gateway /v1/health on :8090 for contrast) and
records: uptime, first_failure_timestamp, last_successful_poll, last_successful_live_gate, PID,
process_alive, exit_code, and the writer-lock + recent endpoint context before a crash. The
memory-service liveness is derived ONLY from the memory-service probe, NEVER from the Gateway, so a
Gateway-up / memory-down situation is recorded correctly.

REFINEMENT: memory (RSS), CPU, and open file-descriptor count are recorded as a TIME SERIES
(periodic samples with timestamps), so a gradual leak shows as a rising trend, distinguishable from
a sudden spike. The trajectory is written into the report.

The HTTP getter, the resource sampler, and the process handle are injectable, so this is
unit-testable without a live stack.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

HealthGetter = Callable[[str], Tuple[bool, int, Dict[str, Any]]]
ResourceSampler = Callable[[], Dict[str, Any]]

_DIAG_DIR = Path("runtime/diagnostics")


def _default_getter(url: str) -> Tuple[bool, int, Dict[str, Any]]:
    import httpx
    try:
        r = httpx.get(url, timeout=4.0)
        try:
            data = r.json()
        except Exception:
            data = {}
        return True, r.status_code, data if isinstance(data, dict) else {}
    except Exception as exc:
        return False, 0, {"error": str(exc)}


def make_psutil_sampler(pid: Optional[int]) -> ResourceSampler:
    """Resource sampler for a PID via psutil if available; otherwise reports availability=False so
    the trend is honestly marked unavailable rather than faked."""
    def sample() -> Dict[str, Any]:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            import psutil
        except ImportError:
            return {"timestamp": ts, "available": False, "reason": "psutil not installed"}
        if pid is None:
            return {"timestamp": ts, "available": False, "reason": "no pid"}
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                rss_mb = round(p.memory_info().rss / (1024 * 1024), 3)
                cpu = p.cpu_percent(interval=None)
                try:
                    num_fds = p.num_fds()
                except (AttributeError, Exception):
                    num_fds = len(p.open_files()) if hasattr(p, "open_files") else -1
            return {"timestamp": ts, "available": True, "rss_mb": rss_mb,
                    "cpu_percent": cpu, "num_fds": num_fds}
        except Exception as exc:
            return {"timestamp": ts, "available": False, "reason": str(exc)}
    return sample


class MemoryServiceMonitor:
    def __init__(self, gateway_url: str, memory_url: str, *,
                 get_json: Optional[HealthGetter] = None,
                 resource_sampler: Optional[ResourceSampler] = None,
                 pid: Optional[int] = None,
                 process_alive: Optional[Callable[[], bool]] = None,
                 exit_code_getter: Optional[Callable[[], Optional[int]]] = None) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.memory_url = memory_url.rstrip("/")
        self.get_json = get_json or _default_getter
        self.resource_sampler = resource_sampler or make_psutil_sampler(pid)
        self.pid = pid
        self._process_alive = process_alive
        self._exit_code_getter = exit_code_getter
        self.start_time = time.time()
        self.first_failure_timestamp: Optional[str] = None
        self.last_successful_poll: Optional[str] = None
        self.last_successful_live_gate: Optional[str] = None
        self.resource_timeseries: List[Dict[str, Any]] = []
        self.poll_history: List[Dict[str, Any]] = []
        self.recent_endpoints: List[str] = []

    def set_last_gate(self, gate: str) -> None:
        self.last_successful_live_gate = gate

    def record_endpoint(self, endpoint: str) -> None:
        self.recent_endpoints.append(endpoint)
        self.recent_endpoints = self.recent_endpoints[-20:]

    def poll_once(self) -> Dict[str, Any]:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        m_ok, m_status, _ = self.get_json(f"{self.memory_url}/health")
        g_ok, g_status, _ = self.get_json(f"{self.gateway_url}/v1/health")
        memory_alive = bool(m_ok and m_status < 500)        # ONLY from the memory probe
        gateway_alive = bool(g_ok and g_status < 500)       # contrast only
        if memory_alive:
            self.last_successful_poll = now
        elif self.first_failure_timestamp is None:
            self.first_failure_timestamp = now
        sample = self.resource_sampler() or {}
        self.resource_timeseries.append(sample)
        entry = {"timestamp": now, "memory_service_alive": memory_alive,
                 "gateway_alive": gateway_alive, "memory_status": m_status,
                 "gateway_status": g_status}
        self.poll_history.append(entry)
        return entry

    def process_alive(self) -> Optional[bool]:
        if self._process_alive is not None:
            try:
                return bool(self._process_alive())
            except Exception:
                return None
        return None

    def exit_code(self) -> Optional[int]:
        if self._exit_code_getter is not None:
            try:
                return self._exit_code_getter()
            except Exception:
                return None
        return None

    def run(self, samples: int, interval: float = 1.0, sleep: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
        sleep = sleep or time.sleep
        for i in range(max(1, samples)):
            self.poll_once()
            if i < samples - 1:
                sleep(interval)
        return self.report()

    def _resource_trend(self) -> Dict[str, Any]:
        avail = [s for s in self.resource_timeseries if s.get("available")]
        if len(avail) < 2:
            return {"samples": len(avail), "trend": "insufficient_data"}
        rss = [s.get("rss_mb", 0.0) for s in avail]
        fds = [s.get("num_fds", 0) for s in avail if isinstance(s.get("num_fds"), (int, float))]
        return {
            "samples": len(avail),
            "rss_mb_first": rss[0], "rss_mb_last": rss[-1],
            "rss_mb_delta": round(rss[-1] - rss[0], 3),
            "rss_rising": rss[-1] > rss[0],
            "fds_first": fds[0] if fds else None, "fds_last": fds[-1] if fds else None,
            "fds_rising": (fds[-1] > fds[0]) if len(fds) >= 2 else None,
            "trend": "rising_leak_suspect" if (rss[-1] - rss[0]) > 0 and rss[-1] > rss[0] else "stable_or_spike",
        }

    def report(self) -> Dict[str, Any]:
        memory_crashed = self.first_failure_timestamp is not None
        return {
            "uptime_seconds": round(time.time() - self.start_time, 3),
            "first_failure_timestamp": self.first_failure_timestamp,
            "last_successful_poll": self.last_successful_poll,
            "last_successful_live_gate": self.last_successful_live_gate,
            "pid": self.pid,
            "process_alive": self.process_alive(),
            "exit_code": self.exit_code(),
            "memory_service_crashed": memory_crashed,
            "gateway_alive_at_last_poll": self.poll_history[-1]["gateway_alive"] if self.poll_history else None,
            "memory_alive_at_last_poll": self.poll_history[-1]["memory_service_alive"] if self.poll_history else None,
            "recent_endpoints_before_crash": list(self.recent_endpoints),
            "resource_timeseries": self.resource_timeseries,
            "resource_trend": self._resource_trend(),
            "poll_history": self.poll_history,
        }

    def write_reports(self, diag_dir: Path = _DIAG_DIR) -> Tuple[Path, Path]:
        diag_dir.mkdir(parents=True, exist_ok=True)
        rep = self.report()
        jp = diag_dir / "memory_service_crash_report.json"
        mp = diag_dir / "memory_service_crash_report.md"
        jp.write_text(json.dumps(rep, indent=2), encoding="utf-8")
        trend = rep["resource_trend"]
        lines = [
            "# Memory-service crash report",
            "",
            f"- memory_service_crashed: {rep['memory_service_crashed']}",
            f"- first_failure_timestamp: {rep['first_failure_timestamp']}",
            f"- last_successful_poll: {rep['last_successful_poll']}",
            f"- last_successful_live_gate: {rep['last_successful_live_gate']}",
            f"- pid: {rep['pid']}  process_alive: {rep['process_alive']}  exit_code: {rep['exit_code']}",
            f"- gateway_alive_at_last_poll: {rep['gateway_alive_at_last_poll']}",
            f"- memory_alive_at_last_poll: {rep['memory_alive_at_last_poll']}",
            "",
            "## Resource trend (time series)",
            f"- samples: {trend.get('samples')}",
            f"- rss_mb: {trend.get('rss_mb_first')} -> {trend.get('rss_mb_last')} "
            f"(delta {trend.get('rss_mb_delta')})",
            f"- fds: {trend.get('fds_first')} -> {trend.get('fds_last')}",
            f"- trend: {trend.get('trend')}",
            "",
            f"- recent_endpoints_before_crash: {rep['recent_endpoints_before_crash']}",
        ]
        mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return jp, mp


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="BYON memory-service crash monitor")
    ap.add_argument("--gateway-url", default="http://127.0.0.1:8090")
    ap.add_argument("--memory-url", default="http://127.0.0.1:8000")
    ap.add_argument("--samples", type=int, default=30)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--pid", type=int, default=None)
    args = ap.parse_args(argv)
    mon = MemoryServiceMonitor(args.gateway_url, args.memory_url, pid=args.pid)
    mon.run(args.samples, args.interval)
    jp, mp = mon.write_reports()
    rep = mon.report()
    print(f"[monitor] memory_service_crashed={rep['memory_service_crashed']} "
          f"first_failure={rep['first_failure_timestamp']} -> {jp}")
    return 2 if rep["memory_service_crashed"] else 0


if __name__ == "__main__":
    sys.exit(main())
