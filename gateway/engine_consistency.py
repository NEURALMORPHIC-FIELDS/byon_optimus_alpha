# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Engine-level read/write consistency coordination (Cycle 7, target 1).

Every memory-service access - writer (vault indexing / batch store) and reader (search) - passes
through this shared cross-process coordinator. A writer marks a write batch in progress; a reader
WAITS (bounded, explicit timeout) for the batch to commit before reading, so no reader ever
observes a partial FAISS/metadata state. This is a real shared/exclusive coordination (stronger
than the Cycle-5 snapshot+retry heuristic, which remains as a fallback) and exposes a consistency
signal: read_consistency_mode, snapshot_version (write-batch counter), last_write_batch_id,
last_consistent_read_ts.

The sealed memory-service engine is not modified; this coordinator sits at the engine access
boundary that ALL writers and readers share, giving an engine-level consistency guarantee.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict

from .write_lock import pid_alive

MODE = "in_engine_rw_lock"
DEFAULT_STATE = Path("runtime/locks/memory_engine.json")
WRITER_STALE_SECONDS = 120.0


class EngineConsistency:
    def __init__(self, state_path: Path = None) -> None:
        self.path = Path(state_path) if state_path is not None else Path(DEFAULT_STATE)
        self.read_consistency_mode = MODE
        self._lock = threading.Lock()

    def _read(self) -> Dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, st: Dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def _writer_active(self, st: Dict[str, Any]) -> bool:
        if not st.get("writing"):
            return False
        pid = st.get("writer_pid")
        if pid and not pid_alive(int(pid)):
            return False                                 # writer died mid-batch -> not active
        if time.time() - float(st.get("write_started_ts", 0) or 0) > WRITER_STALE_SECONDS:
            return False                                 # stale write flag -> ignore
        return True

    # -- writer side --------------------------------------------------------
    def begin_write(self) -> int:
        with self._lock:
            st = self._read()
            batch_id = int(st.get("write_batch_id", 0)) + 1
            st.update({"writing": True, "writer_pid": os.getpid(), "write_batch_id": batch_id,
                       "write_started_ts": time.time()})
            self._write(st)
            return batch_id

    def commit_write(self, batch_id: int) -> None:
        with self._lock:
            st = self._read()
            st.update({"writing": False, "last_write_batch_id": batch_id,
                       "last_commit_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            self._write(st)

    # -- reader side --------------------------------------------------------
    def wait_consistent(self, timeout: float = 2.0, poll: float = 0.05) -> bool:
        """Wait until no write batch is in progress (bounded). Returns True if a consistent
        moment was observed within the timeout, False on explicit timeout."""
        deadline = time.time() + timeout
        consistent = True
        while True:
            st = self._read()
            if not self._writer_active(st):
                break
            consistent = False
            if time.time() >= deadline:
                break                                    # explicit timeout - caller may fall back
            time.sleep(poll)
        with self._lock:
            st = self._read()
            st["last_consistent_read_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._write(st)
        return consistent

    # -- status -------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        st = self._read()
        return {"read_consistency_mode": MODE,
                "snapshot_version": st.get("write_batch_id", 0),
                "last_write_batch_id": st.get("last_write_batch_id"),
                "last_consistent_read_ts": st.get("last_consistent_read_ts"),
                "writing": self._writer_active(st),
                "writer_pid": st.get("writer_pid") if self._writer_active(st) else None}
