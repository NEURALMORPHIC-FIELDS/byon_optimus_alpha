"""BYONLifeLoop v1 — minimal internal circulation over the canonical base.

NOT a new memory authority. It does not store facts, decide truth, or bypass the
memory-service. It only:
  - consumes an internal event stream (interactions, feedback),
  - keeps a small self_state (counters, unknown rate, repetition, feedback pressure),
  - and periodically triggers the EXISTING canonical consolidation (memory-service
    `fce_consolidate`) when interaction count or feedback pressure crosses a threshold.

Truth, grounding, and storage stay entirely in the memory-service + FCE-M + D_Cortex.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())[:160]


class BYONLifeLoop:
    def __init__(self, events_path: str = "runtime/lifeloop/events.jsonl",
                 consolidate_every: Optional[int] = None,
                 pressure_threshold: Optional[float] = None) -> None:
        self.events_path = Path(events_path)
        try:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.consolidate_every = int(consolidate_every if consolidate_every is not None
                                     else os.environ.get("BYON_LIFELOOP_CONSOLIDATE_EVERY", "8"))
        self.pressure_threshold = float(pressure_threshold if pressure_threshold is not None
                                        else os.environ.get("BYON_LIFELOOP_PRESSURE_THRESHOLD", "3.0"))
        self._lock = threading.Lock()
        self._recent: Deque[str] = deque(maxlen=50)
        self.state: Dict[str, Any] = {
            "started_at": _now(), "ticks": 0, "interactions": 0,
            "known": 0, "unknown": 0, "provisional": 0, "disputed": 0, "refused": 0,
            "unknown_rate": 0.0, "repetitions": 0, "feedback_pressure": 0.0,
            "consolidations": 0, "interactions_since_consolidate": 0,
            "last_consolidate_ts": None, "memory_authority": "memory-service (LifeLoop holds none)",
        }

    def _append(self, row: Dict[str, Any]) -> None:
        try:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": _now(), **row}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # -- event stream -------------------------------------------------------
    def record_interaction(self, *, question: str, status: str, user_id: Optional[str] = None) -> None:
        st = (status or "ERROR").upper()
        q = _norm(question)
        with self._lock:
            self.state["interactions"] += 1
            self.state["interactions_since_consolidate"] += 1
            if st == "KNOWN":
                self.state["known"] += 1
            elif st == "UNKNOWN":
                self.state["unknown"] += 1
                self.state["feedback_pressure"] += 0.5          # an UNKNOWN is an attention signal
            elif st.startswith("PROVISIONAL"):
                self.state["provisional"] += 1
            elif st == "DISPUTED":
                self.state["disputed"] += 1
                self.state["feedback_pressure"] += 0.5
            elif st == "REFUSED":
                self.state["refused"] += 1
            tot = max(1, self.state["interactions"])
            self.state["unknown_rate"] = round(self.state["unknown"] / tot, 4)
            if q and q in self._recent:
                self.state["repetitions"] += 1
                if st in ("UNKNOWN", "DISPUTED"):
                    self.state["feedback_pressure"] += 0.5      # repeated unresolved → more pressure
            if q:
                self._recent.append(q)
        self._append({"kind": "interaction", "status": st, "user_id": user_id, "question": q[:120]})

    def record_feedback(self, *, rating: str, user_id: Optional[str] = None) -> None:
        r = (rating or "").lower()
        with self._lock:
            if r in ("wrong", "false", "do_not_remember"):
                self.state["feedback_pressure"] += 1.5
            elif r in ("right", "correct", "important", "remember_this"):
                self.state["feedback_pressure"] = max(0.0, self.state["feedback_pressure"] - 0.5)
        self._append({"kind": "feedback", "rating": r, "user_id": user_id})

    # -- circulation --------------------------------------------------------
    def should_consolidate(self) -> bool:
        with self._lock:
            return (self.state["interactions_since_consolidate"] >= self.consolidate_every
                    or self.state["feedback_pressure"] >= self.pressure_threshold)

    def tick(self, mem_client: Optional[Any] = None) -> Dict[str, Any]:
        """One circulation step. Triggers the canonical consolidation if warranted. Never
        stores facts itself."""
        with self._lock:
            self.state["ticks"] += 1
        consolidated, result = False, None
        if self.should_consolidate():
            if mem_client is not None and hasattr(mem_client, "fce_consolidate"):
                try:
                    result = mem_client.fce_consolidate()
                except Exception as exc:
                    result = {"fce_status": "unavailable", "error": str(exc)}
            with self._lock:
                self.state["consolidations"] += 1
                self.state["interactions_since_consolidate"] = 0
                self.state["feedback_pressure"] = max(0.0, self.state["feedback_pressure"] - self.pressure_threshold)
                self.state["last_consolidate_ts"] = _now()
            consolidated = True
            self._append({"kind": "consolidate", "result": result})
        return {"consolidated": consolidated, "result": result, "self_state": self.snapshot()}

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            s = dict(self.state)
        s["recent_unique_questions"] = len(set(self._recent))
        return s
