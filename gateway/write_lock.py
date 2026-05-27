# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Single-writer lock for vault indexing (Cycle 4, target 3).

A file lock (runtime/locks/vault_training.lock) makes sure only ONE vault trainer writes to the
canonical memory-service at a time, so concurrent writes can't churn the FAISS index under live
readers. The lock records pid / started_at / vault_path / command / heartbeat_at. A second writer
is refused while the holder is alive with a fresh heartbeat; a dead or stale lock is reclaimed
with a warning (so an orphaned writer can never block forever).

Portable PID-liveness: ctypes OpenProcess on Windows, os.kill(pid,0) on POSIX. No psutil dep.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_LOCK = Path("runtime/locks/vault_training.lock")
HEARTBEAT_STALE_SECONDS = 120.0   # a holder silent longer than this is considered stale


def pid_alive(pid: int) -> bool:
    """True if a process with this pid currently exists (best-effort, cross-platform)."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        # distinguish "exists but exited" via exit code 259 (STILL_ACTIVE)
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # exists, owned by someone else
    except OSError:
        return False
    return True


class VaultTrainingLock:
    def __init__(self, lock_path: Optional[Path] = None, *,
                 stale_after: float = HEARTBEAT_STALE_SECONDS) -> None:
        self.path = Path(lock_path) if lock_path is not None else Path(DEFAULT_LOCK)
        self.stale_after = stale_after
        self._held = False

    # -- inspection ---------------------------------------------------------
    def read(self) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None
        except (OSError, json.JSONDecodeError):
            return None

    def status(self) -> Dict[str, Any]:
        rec = self.read()
        if not rec:
            return {"locked": False, "pid": None, "alive": False, "stale": False,
                    "indexing_in_progress": False}
        pid = rec.get("pid")
        alive = pid_alive(int(pid)) if pid else False
        age = time.time() - float(rec.get("heartbeat_at", 0) or 0)
        stale = (not alive) or age > self.stale_after
        return {"locked": True, "pid": pid, "alive": alive, "stale": stale,
                "indexing_in_progress": bool(alive and not stale),
                "vault_path": rec.get("vault_path"), "command": rec.get("command"),
                "started_at": rec.get("started_at"), "heartbeat_age_s": round(age, 1)}

    # -- acquire / heartbeat / release -------------------------------------
    def _write(self, rec: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def acquire(self, *, vault_path: str = "", command: str = "") -> Dict[str, Any]:
        """Returns {'acquired': bool, 'reason': str, 'reclaimed': bool}. Refuses if a live,
        fresh holder exists; reclaims a dead/stale lock with a warning."""
        st = self.status()
        reclaimed = False
        if st["locked"] and st["indexing_in_progress"] and st["pid"] != os.getpid():
            return {"acquired": False, "reason": f"active writer pid={st['pid']} "
                    f"(heartbeat {st['heartbeat_age_s']}s ago)", "reclaimed": False, "holder": st}
        if st["locked"]:
            reclaimed = True   # dead or stale -> take it over
        now = time.time()
        self._write({"pid": os.getpid(), "vault_path": vault_path, "command": command,
                     "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                     "started_ts": now, "heartbeat_at": now})
        self._held = True
        return {"acquired": True, "reason": "reclaimed stale lock" if reclaimed else "acquired",
                "reclaimed": reclaimed}

    def heartbeat(self) -> None:
        if not self._held:
            return
        rec = self.read() or {}
        if rec.get("pid") == os.getpid():
            rec["heartbeat_at"] = time.time()
            try:
                self._write(rec)
            except OSError:
                pass

    def release(self) -> None:
        rec = self.read()
        if rec and rec.get("pid") == os.getpid():
            try:
                self.path.unlink()
            except OSError:
                pass
        self._held = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
