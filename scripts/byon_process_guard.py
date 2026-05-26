#!/usr/bin/env python
"""BYON process guard (Cycle 4, target 4).

Orphaned vault-training processes once kept writing to the FAISS index and churned live
retrieval — and because the interpreter is named `python3.13` (not `python.exe`), naive
`python.exe` kills missed them. This guard detects ONLY BYON vault-training writers (by command
line), across `python.exe` / `python3.13.exe` / `py.exe`, and never touches unrelated Python.

  python scripts/byon_process_guard.py status              # lock + active writers + orphan warning
  python scripts/byon_process_guard.py stop-stale          # stop orphan writers (not the lock holder)
  python scripts/byon_process_guard.py stop-vault-trainers # stop every vault-training writer

The detection/filter logic is pure (takes a process list) so it is unit-tested without real
processes; only `list_processes()` touches the OS.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gateway.write_lock import VaultTrainingLock, pid_alive  # noqa: E402

# a vault-training writer: a python interpreter whose command line runs the trainer
VAULT_TRAINER_RE = re.compile(r"train[_-]?vault|vault_training|--train-vault", re.IGNORECASE)
_PY_NAME_RE = re.compile(r"^(python(3(\.\d+)?)?|py)(\.exe)?$", re.IGNORECASE)
_PY_CMD_RE = re.compile(r"\bpython(3(\.\d+)?)?(\.exe)?\b", re.IGNORECASE)


def is_python(name: str, cmdline: str) -> bool:
    if name and _PY_NAME_RE.match(name.strip()):
        return True
    return bool(_PY_CMD_RE.search(cmdline or ""))


def is_vault_trainer(name: str, cmdline: str) -> bool:
    """A BYON vault-training writer — python interpreter + the trainer in its command line.
    Deliberately NARROW so unrelated python processes are never matched."""
    return is_python(name, cmdline) and bool(VAULT_TRAINER_RE.search(cmdline or ""))


def find_vault_trainers(procs: List[Dict[str, Any]], *, self_pid: Optional[int] = None
                        ) -> List[Dict[str, Any]]:
    self_pid = os.getpid() if self_pid is None else self_pid
    out = []
    for p in procs:
        pid = p.get("pid")
        if pid == self_pid:
            continue
        if is_vault_trainer(p.get("name", ""), p.get("cmdline", "")):
            out.append({"pid": pid, "name": p.get("name", ""), "cmdline": (p.get("cmdline") or "")[:200]})
    return out


def list_processes() -> List[Dict[str, Any]]:
    """[{pid, name, cmdline}] for all processes (best-effort, cross-platform)."""
    if os.name == "nt":
        import subprocess
        ps = ("Get-CimInstance Win32_Process | "
              "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress")
        try:
            raw = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=30).stdout
            data = json.loads(raw) if raw.strip() else []
            if isinstance(data, dict):
                data = [data]
            return [{"pid": d.get("ProcessId"), "name": d.get("Name") or "",
                     "cmdline": d.get("CommandLine") or ""} for d in data]
        except Exception:
            return []
    else:
        import subprocess
        try:
            raw = subprocess.run(["ps", "-eo", "pid=,comm=,args="], capture_output=True,
                                 text=True, timeout=30).stdout
        except Exception:
            return []
        procs = []
        for line in raw.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) >= 2:
                try:
                    pid = int(parts[0])
                except ValueError:
                    continue
                name = parts[1]
                cmd = parts[2] if len(parts) > 2 else ""
                procs.append({"pid": pid, "name": name, "cmdline": f"{name} {cmd}"})
        return procs


def status() -> Dict[str, Any]:
    lock = VaultTrainingLock().status()
    trainers = find_vault_trainers(list_processes())
    holder_pid = lock.get("pid") if lock.get("indexing_in_progress") else None
    orphans = [t for t in trainers if t["pid"] != holder_pid]
    return {
        "lock": lock,
        "active_writers": trainers,
        "active_writer_pid": holder_pid,
        "orphan_writers": orphans,
        "orphan_writer_warning": bool(orphans) and not lock.get("indexing_in_progress"),
        "duplicate_writer": len(trainers) > 1,
    }


def _stop(pids: List[int]) -> List[int]:
    stopped = []
    for pid in pids:
        if not pid:
            continue
        try:
            if os.name == "nt":
                import ctypes
                h = ctypes.windll.kernel32.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
                if h:
                    ctypes.windll.kernel32.TerminateProcess(h, 1)
                    ctypes.windll.kernel32.CloseHandle(h)
                    stopped.append(pid)
            else:
                import signal
                os.kill(int(pid), signal.SIGTERM)
                stopped.append(pid)
        except Exception:
            pass
    return stopped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["status", "stop-stale", "stop-vault-trainers"])
    args = ap.parse_args()
    st = status()
    if args.command == "status":
        print(json.dumps(st, indent=2))
        return 0
    if args.command == "stop-stale":
        pids = [t["pid"] for t in st["orphan_writers"]]
        stopped = _stop(pids)
        print(json.dumps({"stopped_stale": stopped, "kept_active_writer": st["active_writer_pid"]}, indent=2))
        # if the lock is stale/dead, reclaim-free it too
        if st["lock"].get("stale"):
            try:
                VaultTrainingLock().path.unlink()
            except OSError:
                pass
        return 0
    # stop-vault-trainers
    stopped = _stop([t["pid"] for t in st["active_writers"]])
    print(json.dumps({"stopped_vault_trainers": stopped}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
