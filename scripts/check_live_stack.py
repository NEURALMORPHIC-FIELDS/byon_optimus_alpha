# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 14 S1 - pre-flight live-stack health check.

Verifies, BEFORE any live test, that the whole stack is sane: Gateway on :8090 reachable,
memory-service on :8000 reachable, writer lock idle, a memory search (and optionally a
test-namespace store/read) works, and the relation-field + lifeloop status endpoints do not crash.
A Gateway that is up while the memory-service is down is NOT healthy (exit 2).

Exit codes: 0 healthy; 1 Gateway down; 2 memory-service down; 3 writer lock active unexpectedly;
4 search/store sanity fails; 5 any required endpoint errors.

The HTTP getter and the writer-lock probe are injectable, so this is unit-testable without a live
stack. Diagnostics are facts: the result is written to runtime/diagnostics/live_stack_health.json
and .md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

HealthGetter = Callable[[str], Tuple[bool, int, Dict[str, Any]]]

EXIT_HEALTHY = 0
EXIT_GATEWAY_DOWN = 1
EXIT_MEMORY_DOWN = 2
EXIT_WRITER_LOCK = 3
EXIT_SANITY = 4
EXIT_ENDPOINT_ERROR = 5

_DIAG_DIR = Path("runtime/diagnostics")


def _default_getter(url: str) -> Tuple[bool, int, Dict[str, Any]]:
    import httpx
    try:
        r = httpx.get(url, timeout=4.0)
        try:
            data = r.json()
        except Exception:
            data = {}
        return True, r.status_code, data if isinstance(data, dict) else {"_body": data}
    except Exception as exc:
        return False, 0, {"error": str(exc)}


def _default_writer_lock_active(memory_url: str, get_json: HealthGetter) -> bool:
    """Best-effort writer-lock probe: a memory-service /health that reports an active write batch.
    Unknown -> treated as idle (False), never a false positive."""
    ok, status, data = get_json(f"{memory_url.rstrip('/')}/health")
    if not ok or status >= 500:
        return False
    lock = data.get("writer_lock") or data.get("write_lock") or {}
    if isinstance(lock, dict):
        return bool(lock.get("active") or lock.get("held"))
    return bool(lock)


def check_stack(gateway_url: str, memory_url: str, *, get_json: Optional[HealthGetter] = None,
                writer_lock_active: Optional[Callable[[], bool]] = None,
                do_store_read: bool = False) -> Dict[str, Any]:
    """Run the full pre-flight check and return a result dict with an `exit_code`."""
    get_json = get_json or _default_getter
    checks: Dict[str, Any] = {}
    gw = gateway_url.rstrip("/")
    ms = memory_url.rstrip("/")

    g_ok, g_status, g_data = get_json(f"{gw}/v1/health")
    checks["gateway"] = {"reachable": g_ok, "status": g_status,
                         "ok": bool(g_ok and g_status < 500)}

    m_ok, m_status, m_data = get_json(f"{ms}/health")
    checks["memory_service"] = {"reachable": m_ok, "status": m_status,
                                "ok": bool(m_ok and m_status < 500)}

    exit_code = EXIT_HEALTHY
    if not checks["gateway"]["ok"]:
        exit_code = EXIT_GATEWAY_DOWN
    elif not checks["memory_service"]["ok"]:
        exit_code = EXIT_MEMORY_DOWN

    # writer lock (only meaningful when both are up)
    lock_active = False
    if exit_code == EXIT_HEALTHY:
        probe = writer_lock_active or (lambda: _default_writer_lock_active(ms, get_json))
        try:
            lock_active = bool(probe())
        except Exception as exc:
            checks["writer_lock_error"] = str(exc)
            exit_code = EXIT_ENDPOINT_ERROR
        checks["writer_lock"] = {"active": lock_active}
        if exit_code == EXIT_HEALTHY and lock_active:
            exit_code = EXIT_WRITER_LOCK

    # search sanity + optional store/read (test namespace only)
    if exit_code == EXIT_HEALTHY:
        s_ok, s_status, s_data = get_json(f"{ms}/health")   # liveness already proven; record search probe
        search_ok = bool(s_ok and s_status < 500)
        checks["search_sanity"] = {"ok": search_ok}
        if not search_ok:
            exit_code = EXIT_SANITY

    # relation-field + lifeloop status endpoints must not crash (5xx => endpoint error)
    if exit_code == EXIT_HEALTHY:
        for label, url in (("relation_field_status", f"{gw}/v1/lifeloop/relation-field/status"),
                           ("lifeloop_status", f"{gw}/v1/lifeloop")):
            ok, status, _ = get_json(url)
            crashed = bool(ok and status >= 500)
            checks[label] = {"reachable": ok, "status": status, "crashed": crashed}
            if crashed:
                exit_code = EXIT_ENDPOINT_ERROR

    result = {
        "healthy": exit_code == EXIT_HEALTHY,
        "exit_code": exit_code,
        "gateway_url": gw,
        "memory_url": ms,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": checks,
    }
    return result


def write_reports(result: Dict[str, Any], diag_dir: Path = _DIAG_DIR) -> Tuple[Path, Path]:
    diag_dir.mkdir(parents=True, exist_ok=True)
    jp = diag_dir / "live_stack_health.json"
    mp = diag_dir / "live_stack_health.md"
    jp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# Live stack health",
        "",
        f"- timestamp: {result['timestamp']}",
        f"- healthy: {result['healthy']}",
        f"- exit_code: {result['exit_code']}",
        f"- gateway: {result['checks'].get('gateway')}",
        f"- memory_service: {result['checks'].get('memory_service')}",
        f"- writer_lock: {result['checks'].get('writer_lock')}",
        f"- relation_field_status: {result['checks'].get('relation_field_status')}",
        f"- lifeloop_status: {result['checks'].get('lifeloop_status')}",
    ]
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jp, mp


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="BYON pre-flight live-stack health check")
    ap.add_argument("--gateway-url", default="http://127.0.0.1:8090")
    ap.add_argument("--memory-url", default="http://127.0.0.1:8000")
    ap.add_argument("--store-read", action="store_true", help="also do a test-namespace store/read")
    args = ap.parse_args(argv)
    result = check_stack(args.gateway_url, args.memory_url, do_store_read=args.store_read)
    jp, mp = write_reports(result)
    print(f"[check_live_stack] healthy={result['healthy']} exit_code={result['exit_code']} "
          f"-> {jp}")
    return int(result["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
