# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S4 - memory-service crash reproduction (outside the full harness).

Drives the stack with a controlled request pattern to try to reproduce the "memory-service dies
mid-run while Gateway stays up" symptom WITHOUT the full live harness, so a crash can be observed
and attributed to a specific endpoint pattern.

Modes:
  search           repeated memory-grounded chat / search
  relation         relation-field status / context endpoints
  lifeloop         lifeloop status / tick
  store-read       store then read loops
  mixed            approximates the live-harness request pattern (all of the above interleaved)
  acquisition-store  store_batch (batched writes) + the epistemic-acquisition query path, so the
                     CURRENT (13.3) surface is exercised, not only the 13.1 one

Config (env): BYON_CRASH_REPRO_ITERATIONS=200, BYON_CRASH_REPRO_CONCURRENCY=1,
BYON_CRASH_REPRO_DELAY_MS=50, BYON_CRASH_REPRO_STOP_ON_FAILURE=true.

The HTTP `call` and the memory `health` probe are injectable, so this is unit-testable without a
live stack. A service crash is recorded as a service crash (endpoint + iteration), never masked.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

Caller = Callable[[str, str, Dict[str, Any]], Tuple[bool, int, Dict[str, Any]]]
HealthProbe = Callable[[], bool]

_DIAG_DIR = Path("runtime/diagnostics")

_USER = {"user_id": "crash_repro_user", "session_id": "crash_repro_session"}


def _endpoints(mode: str, gw: str, ms: str) -> List[Dict[str, Any]]:
    chat = {"label": "chat_search", "method": "POST", "url": f"{gw}/v1/chat",
            "payload": {**_USER, "message": "what operational level is BYON?"}}
    relation = {"label": "relation_status", "method": "GET",
                "url": f"{gw}/v1/lifeloop/relation-field/status", "payload": {}}
    lifeloop = {"label": "lifeloop_status", "method": "GET", "url": f"{gw}/v1/lifeloop", "payload": {}}
    store = {"label": "memory_store", "method": "POST", "url": f"{ms}/",
             "payload": {"action": "store", "type": "fact",
                         "data": {"fact": "crash repro probe fact", "source": "repro",
                                  "thread_id": _USER["user_id"], "trust": "EXTRACTED_USER_CLAIM"}}}
    read = {"label": "memory_search", "method": "POST", "url": f"{ms}/",
            "payload": {"action": "search", "type": "fact", "query": "crash repro probe",
                        "thread_id": _USER["user_id"], "scope": "thread", "top_k": 5}}
    store_batch = {"label": "memory_store_batch", "method": "POST", "url": f"{ms}/",
                   "payload": {"action": "store_batch", "type": "fact", "data": {"items": [
                       {"fact": f"batch repro fact {i}", "source": f"repro:{i}",
                        "thread_id": _USER["user_id"], "trust": "EXTRACTED_USER_CLAIM"}
                       for i in range(8)]}}}
    acquisition = {"label": "research_acquisition", "method": "POST", "url": f"{gw}/v1/research",
                   "payload": {**_USER, "question": "what is BYON architecture?", "allow_web": False}}
    table = {
        "search": [chat, read],
        "relation": [relation],
        "lifeloop": [lifeloop],
        "store-read": [store, read],
        "mixed": [chat, relation, lifeloop, store, read],
        "acquisition-store": [store_batch, acquisition, read],
    }
    return table.get(mode, table["mixed"])


class CrashReproducer:
    def __init__(self, gateway_url: str, memory_url: str, *, mode: str = "mixed",
                 call: Optional[Caller] = None, health: Optional[HealthProbe] = None,
                 iterations: int = 200, concurrency: int = 1, delay_ms: int = 50,
                 stop_on_failure: bool = True, sleep: Optional[Callable[[float], None]] = None) -> None:
        self.gw = gateway_url.rstrip("/")
        self.ms = memory_url.rstrip("/")
        self.mode = mode
        self.call = call or _default_caller
        self.health = health or (lambda: _default_health(self.ms))
        self.iterations = iterations
        self.concurrency = concurrency
        self.delay_ms = delay_ms
        self.stop_on_failure = stop_on_failure
        self.sleep = sleep or time.sleep

    def run(self) -> Dict[str, Any]:
        endpoints = _endpoints(self.mode, self.gw, self.ms)
        memory_alive_start = self.health()
        first_failure_iteration: Optional[int] = None
        endpoint_at_failure: Optional[str] = None
        last_successful_endpoint: Optional[str] = None
        exceptions: List[str] = []
        completed = 0
        for i in range(self.iterations):
            ep = endpoints[i % len(endpoints)]
            try:
                ok, status, _ = self.call(ep["method"], ep["url"], ep.get("payload", {}))
            except Exception as exc:
                ok, status = False, 0
                exceptions.append(f"{ep['label']}: {str(exc)[:160]}")
            completed = i + 1
            # the decisive signal: is the MEMORY-SERVICE still alive? (gateway may stay up)
            if not self.health():
                first_failure_iteration = i
                endpoint_at_failure = ep["label"]
                if self.stop_on_failure:
                    break
            else:
                last_successful_endpoint = ep["label"]
            if self.delay_ms:
                self.sleep(self.delay_ms / 1000.0)
        memory_alive_end = self.health()
        gw_ok, gw_status, _ = self.call("GET", f"{self.gw}/v1/health", {})
        crashed = first_failure_iteration is not None or not memory_alive_end
        suspected = None
        if crashed:
            suspected = (f"memory-service died at endpoint '{endpoint_at_failure}' "
                         f"(iteration {first_failure_iteration}) while gateway_alive={bool(gw_ok and gw_status < 500)}")
        return {
            "mode": self.mode,
            "iterations_requested": self.iterations,
            "iterations_completed": completed,
            "concurrency": self.concurrency,
            "first_failure_iteration": first_failure_iteration,
            "endpoint_at_failure": endpoint_at_failure,
            "last_successful_endpoint": last_successful_endpoint,
            "memory_service_alive_start": memory_alive_start,
            "memory_service_alive_end": memory_alive_end,
            "gateway_alive_end": bool(gw_ok and gw_status < 500),
            "crashed": crashed,
            "exception_summary": exceptions[:20],
            "suspected_trigger": suspected,
            "logs_collected": [str(Path("runtime/logs/memory_service_stdout.log")),
                               str(Path("runtime/logs/memory_service_stderr.log"))],
        }

    def write_reports(self, report: Dict[str, Any], diag_dir: Path = _DIAG_DIR) -> Tuple[Path, Path]:
        diag_dir.mkdir(parents=True, exist_ok=True)
        jp = diag_dir / "crash_repro_report.json"
        mp = diag_dir / "crash_repro_report.md"
        jp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        lines = [
            "# Memory-service crash reproduction",
            "",
            f"- mode: {report['mode']}",
            f"- iterations: {report['iterations_completed']}/{report['iterations_requested']} "
            f"(concurrency {report['concurrency']})",
            f"- crashed: {report['crashed']}",
            f"- first_failure_iteration: {report['first_failure_iteration']}",
            f"- endpoint_at_failure: {report['endpoint_at_failure']}",
            f"- last_successful_endpoint: {report['last_successful_endpoint']}",
            f"- memory_service_alive_start/end: {report['memory_service_alive_start']} / "
            f"{report['memory_service_alive_end']}",
            f"- gateway_alive_end: {report['gateway_alive_end']}",
            f"- suspected_trigger: {report['suspected_trigger']}",
            f"- exception_summary: {report['exception_summary']}",
        ]
        mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return jp, mp


def _default_caller(method: str, url: str, payload: Dict[str, Any]) -> Tuple[bool, int, Dict[str, Any]]:
    import httpx
    try:
        if method == "GET":
            r = httpx.get(url, timeout=10.0)
        else:
            r = httpx.post(url, json=payload, timeout=30.0)
        try:
            data = r.json()
        except Exception:
            data = {}
        return True, r.status_code, data if isinstance(data, dict) else {}
    except Exception as exc:
        return False, 0, {"error": str(exc)}


def _default_health(memory_url: str) -> bool:
    import httpx
    try:
        r = httpx.get(f"{memory_url.rstrip('/')}/health", timeout=4.0)
        return r.status_code < 500
    except Exception:
        return False


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="BYON memory-service crash reproduction")
    ap.add_argument("--gateway-url", default="http://127.0.0.1:8090")
    ap.add_argument("--memory-url", default="http://127.0.0.1:8000")
    ap.add_argument("--mode", default="mixed",
                    choices=["search", "relation", "lifeloop", "store-read", "mixed", "acquisition-store"])
    args = ap.parse_args(argv)
    rep = CrashReproducer(
        args.gateway_url, args.memory_url, mode=args.mode,
        iterations=int(os.environ.get("BYON_CRASH_REPRO_ITERATIONS", "200")),
        concurrency=int(os.environ.get("BYON_CRASH_REPRO_CONCURRENCY", "1")),
        delay_ms=int(os.environ.get("BYON_CRASH_REPRO_DELAY_MS", "50")),
        stop_on_failure=os.environ.get("BYON_CRASH_REPRO_STOP_ON_FAILURE", "true").strip().lower()
        in ("1", "true", "yes", "on"),
    ).run()
    repro = CrashReproducer(args.gateway_url, args.memory_url, mode=args.mode)
    jp, mp = repro.write_reports(rep)
    print(f"[crash_repro] mode={rep['mode']} crashed={rep['crashed']} "
          f"first_failure_iteration={rep['first_failure_iteration']} -> {jp}")
    return 2 if rep["crashed"] else 0


if __name__ == "__main__":
    sys.exit(main())
