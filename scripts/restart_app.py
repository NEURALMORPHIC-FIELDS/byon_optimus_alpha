#!/usr/bin/env python
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Stop the running BYON app and relaunch it detached, then wait for gateway health.

Used by the restart-recall gate's `--phase auto`. Best-effort and platform-aware (Windows /
POSIX). Frees the gateway / memory-service / UI ports, relaunches `run_byon.py --no-prompt`,
and polls /v1/health until the gateway is back (or a timeout is hit)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTS = (8090, 8000, 7860)
HEALTH = "http://127.0.0.1:8090/v1/health"


def _free_ports() -> None:
    if os.name == "nt":
        ps = (
            "$ports=8090,8000,7860; "
            "$pids=Get-NetTCPConnection -State Listen -LocalPort $ports -ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty OwningProcess -Unique; "
            "foreach($p in $pids){ try{ Stop-Process -Id $p -Force -ErrorAction Stop }catch{} } "
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -match 'run_byon' } | "
            "ForEach-Object { try{ Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop }catch{} }"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, timeout=60)
    else:
        subprocess.run("pkill -f run_byon.py || true", shell=True, check=False)
    time.sleep(2)


def _relaunch() -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    log = (ROOT / "runtime" / "relaunch_auto.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log, "ab")
    kwargs = {"cwd": str(ROOT), "stdout": fh, "stderr": fh, "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "run_byon.py", "--no-prompt"], **kwargs)


def _wait_health(timeout_s: int = 300) -> bool:
    import httpx
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            httpx.get(HEALTH, timeout=3)
            return True
        except Exception:
            time.sleep(5)
    return False


def main() -> int:
    print("[restart] freeing ports", PORTS)
    _free_ports()
    print("[restart] relaunching run_byon.py")
    _relaunch()
    ok = _wait_health()
    print("[restart] gateway up" if ok else "[restart] gateway did NOT come up in time")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
