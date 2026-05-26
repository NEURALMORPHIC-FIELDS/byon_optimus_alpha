"""Memory pressure model (Cycle 6, target 2).

LifeLoop v2 keeps a small per-topic "pressure" signal — how much an area of memory is unresolved
or contested — so consolidation and internal research are driven by NEED, not only a fixed count.
This is an attention signal, NOT a truth authority: it never stores facts or decides answers.

Rules (pressure delta):
  UNKNOWN +1 · PROVISIONAL +0.5 · DISPUTED +2 · repeated UNKNOWN same topic +2 (extra) ·
  negative feedback +3 · correction +2 · high-stress research +1 ·
  secret/refused: NO research pressure (safety counter only) ·
  accepted/correct feedback -1 · consolidation success -2.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# recommended actions
CONSOLIDATE = "consolidate"
ASK_USER_FOR_SOURCE = "ask_user_for_source"
SCHEDULE_RESEARCH = "schedule_research"
MARK_DISPUTED = "mark_disputed"
IGNORE_SAFE_SECRET = "ignore_safe_secret"
NO_ACTION = "no_action"


def topic_of(question: str) -> str:
    return re.sub(r"\s+", " ", (question or "").strip().lower()).rstrip("?.! ")[:80] or "unspecified"


class PressureModel:
    def __init__(self, path: str = "runtime/lifeloop/pressure_state.json") -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.topics: Dict[str, Dict[str, Any]] = {}
        self.safety_counter = 0           # secret/refused observations (never research pressure)
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.topics = d.get("topics", {})
                self.safety_counter = d.get("safety_counter", 0)
        except (OSError, json.JSONDecodeError):
            self.topics = {}

    def _persist(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"topics": self.topics, "total": self.total(),
                                       "safety_counter": self.safety_counter}, indent=2,
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def _rec(self, topic: str) -> Dict[str, Any]:
        return self.topics.setdefault(topic, {
            "topic": topic, "pressure": 0.0, "unknown_count": 0, "provisional_count": 0,
            "disputed_count": 0, "correction_count": 0, "last_seen": None, "last_seen_ts": 0.0,
            "success_count": 0, "fail_count": 0, "frozen": False,
            "related_event_ids": [], "recommended_action": NO_ACTION})

    def _touch(self, rec: Dict[str, Any]) -> None:
        rec["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec["last_seen_ts"] = time.time()

    def priority(self, topic: str) -> float:
        """priority = pressure + unresolved_count + disputed_bonus - recent_success_bonus."""
        r = self.topics.get(topic) or {}
        unresolved = r.get("unknown_count", 0) + r.get("provisional_count", 0)
        return round(r.get("pressure", 0.0) + unresolved + 2.0 * r.get("disputed_count", 0)
                     - 1.0 * r.get("success_count", 0), 3)

    def _recommend(self, rec: Dict[str, Any]) -> str:
        if rec["disputed_count"] > 0:
            return MARK_DISPUTED
        if rec["correction_count"] > 0:
            return CONSOLIDATE
        if rec["unknown_count"] >= 2:
            return SCHEDULE_RESEARCH
        if rec["provisional_count"] >= 2:
            return SCHEDULE_RESEARCH
        if rec["unknown_count"] == 1:
            return ASK_USER_FOR_SOURCE
        return NO_ACTION

    # -- observations -------------------------------------------------------
    def observe(self, *, topic: str, status: str, event_id: Optional[str] = None,
                stress_high: bool = False, is_secret: bool = False) -> float:
        st = (status or "").upper()
        with self._lock:
            if is_secret or st == "REFUSED":
                self.safety_counter += 1          # safety only — never a research signal
                rec = self._rec(topic)
                rec["recommended_action"] = IGNORE_SAFE_SECRET if is_secret else rec["recommended_action"]
                self._persist()
                return 0.0
            rec = self._rec(topic)
            delta = 0.0
            if st == "UNKNOWN":
                rec["unknown_count"] += 1
                delta += 1.0
                if rec["unknown_count"] >= 2:
                    delta += 2.0                  # repeated UNKNOWN on the same topic
            elif st.startswith("PROVISIONAL"):
                rec["provisional_count"] += 1
                delta += 0.5
            elif st == "DISPUTED":
                rec["disputed_count"] += 1
                delta += 2.0
            if stress_high:
                delta += 1.0
            rec["pressure"] = round(rec["pressure"] + delta, 3)
            self._touch(rec)
            if event_id:
                rec["related_event_ids"] = (rec["related_event_ids"] + [event_id])[-20:]
            rec["recommended_action"] = self._recommend(rec)
            self._persist()
            return delta

    def feedback(self, *, topic: str, rating: str, event_id: Optional[str] = None) -> float:
        r = (rating or "").lower()
        with self._lock:
            rec = self._rec(topic)
            delta = 0.0
            if r in ("wrong", "false", "do_not_remember"):
                delta = 3.0
                rec["correction_count"] += 1      # negative feedback implies a needed correction
            elif r in ("right", "correct", "important", "remember_this", "partially_correct"):
                delta = -1.0
            rec["pressure"] = round(max(0.0, rec["pressure"] + delta), 3)
            if event_id:
                rec["related_event_ids"] = (rec["related_event_ids"] + [event_id])[-20:]
            rec["recommended_action"] = self._recommend(rec)
            self._persist()
            return delta

    def correction(self, *, topic: str, event_id: Optional[str] = None) -> float:
        with self._lock:
            rec = self._rec(topic)
            rec["correction_count"] += 1
            rec["pressure"] = round(rec["pressure"] + 2.0, 3)
            rec["recommended_action"] = self._recommend(rec)
            if event_id:
                rec["related_event_ids"] = (rec["related_event_ids"] + [event_id])[-20:]
            self._persist()
            return 2.0

    def decay(self, rate_per_hour: float = 0.5, now: Optional[float] = None) -> None:
        """Time-based decay: unattended pressure slowly fades (an old worry matters less)."""
        now = now if now is not None else time.time()
        with self._lock:
            changed = False
            for rec in self.topics.values():
                if rec.get("frozen") or rec["pressure"] <= 0:
                    continue
                dt = now - float(rec.get("last_seen_ts", 0) or 0)
                if dt <= 0:
                    continue
                rec["pressure"] = round(max(0.0, rec["pressure"] - rate_per_hour * (dt / 3600.0)), 3)
                changed = True
            if changed:
                self._persist()

    def task_outcome(self, *, topic: str, success: bool, disputed: bool = False) -> None:
        """A successful internal task relieves pressure; a failed one keeps/raises it; disputed
        evidence neither clears nor loops."""
        with self._lock:
            rec = self._rec(topic)
            if disputed:
                rec["disputed_count"] += 1            # contested — keep pressure, mark disputed
            elif success:
                rec["success_count"] += 1
                rec["pressure"] = round(max(0.0, rec["pressure"] - 1.0), 3)
            else:
                rec["fail_count"] += 1
                rec["pressure"] = round(rec["pressure"] + 1.0, 3)
            rec["recommended_action"] = self._recommend(rec)
            self._persist()

    def freeze(self, topic: str) -> None:
        with self._lock:
            self._rec(topic)["frozen"] = True
            self._persist()

    def relieve_topic(self, topic: str, amount: float = 1.0) -> None:
        with self._lock:
            rec = self.topics.get(topic)
            if rec:
                rec["pressure"] = round(max(0.0, rec["pressure"] - amount), 3)
                self._persist()

    def relieve(self, amount: float = 2.0) -> float:
        """Consolidation success relieves pressure (highest-pressure topics first)."""
        with self._lock:
            remaining = amount
            for rec in sorted(self.topics.values(), key=lambda r: r["pressure"], reverse=True):
                if remaining <= 0:
                    break
                take = min(rec["pressure"], remaining)
                rec["pressure"] = round(rec["pressure"] - take, 3)
                remaining -= take
                rec["recommended_action"] = self._recommend(rec)
            self._persist()
            return amount - remaining

    # -- queries ------------------------------------------------------------
    def total(self) -> float:
        return round(sum(r["pressure"] for r in self.topics.values()), 3)

    def top(self, n: int = 5) -> List[Dict[str, Any]]:
        return sorted([r for r in self.topics.values() if r["pressure"] > 0],
                      key=lambda r: r["pressure"], reverse=True)[:n]

    def get(self, topic: str) -> Optional[Dict[str, Any]]:
        return self.topics.get(topic)
