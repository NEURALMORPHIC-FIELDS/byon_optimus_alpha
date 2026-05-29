# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""BYONLifeLoop v2 - real internal circulation over the hardened memory substrate.

NOT a mind, NOT a new truth authority, and it NEVER answers the user. It only:
  - ingests interaction / feedback / memory / consolidation / tombstone / vault events,
  - keeps a per-topic PRESSURE signal (unresolved / contested areas),
  - files internal RESEARCH TASKS for repeated unknowns (web needs user permission),
  - triggers the EXISTING canonical FCE-M consolidation when pressure/events warrant it,
  - records temporal self-state snapshots so BYON can say what it has learned / what it is
    working on internally.

Truth, grounding, storage and promotion stay entirely in the memory-service + FCE-M + D_Cortex,
governed by the existing ContinuousLearning policy. Secrets never create research tasks and are
never stored in the event stream (content is redacted).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from gateway.pressure import PressureModel, topic_of, SCHEDULE_RESEARCH
from gateway.research_tasks import ResearchTaskQueue

VERSION = "v2"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())[:160]


def _is_secret(question: str, query_class: Optional[str], source_class: Optional[str]) -> bool:
    if query_class == "secret":
        return True
    try:
        from gateway.epistemic_search import is_secret_query
        return bool(is_secret_query(question))
    except Exception:
        return False


class BYONLifeLoop:
    def __init__(self, events_path: str = "runtime/lifeloop/events.jsonl",
                 consolidate_every: Optional[int] = None,
                 pressure_threshold: Optional[float] = None,
                 runtime_dir: Optional[str] = None) -> None:
        self.events_path = Path(events_path)
        rt = Path(runtime_dir) if runtime_dir else self.events_path.parent
        self.runtime_dir = rt
        try:
            rt.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.consolidate_every = int(consolidate_every if consolidate_every is not None
                                     else os.environ.get("BYON_LIFELOOP_CONSOLIDATE_EVERY", "8"))
        self.pressure_threshold = float(pressure_threshold if pressure_threshold is not None
                                        else os.environ.get("BYON_LIFELOOP_PRESSURE_THRESHOLD", "3.0"))
        self.pressure = PressureModel(path=str(rt / "pressure_state.json"))
        self.tasks = ResearchTaskQueue(path=str(rt / "research_tasks.jsonl"))
        self.consolidation_log = rt / "consolidation_log.jsonl"
        self.snapshots_path = rt / "self_state_snapshots.jsonl"
        self.task_results_path = rt / "task_results.jsonl"
        self.task_exec_log = rt / "task_execution_log.jsonl"
        self._task_runner = None          # set by the app; runs a memory-only task -> result dict
        self._candidate_consolidator = None   # set by the app; moves candidate states (commit/dispute/...)
        self._candidate_status_provider = None
        self.last_auto_run_task = None
        self.last_task_result = None
        self.last_candidate_decisions = []
        # Cycle 15: scheduled relation maintenance + gap scan (bounded, autonomous, never truth)
        _on = lambda k, d: os.environ.get(k, d).strip().lower() in ("1", "true", "yes", "on")
        self.relation_maintenance_enabled = _on("BYON_RELATION_MAINTENANCE_ENABLED", "true")
        self.maintenance_every_ticks = int(os.environ.get("BYON_RELATION_MAINTENANCE_EVERY_TICKS", "5"))
        self.gap_scan_every_ticks = int(os.environ.get("BYON_RELATION_GAP_SCAN_EVERY_TICKS", "5"))
        self.autorun_memory_tasks = _on("BYON_RELATION_AUTORUN_MEMORY_TASKS", "true")
        self.max_tasks_per_tick = int(os.environ.get("BYON_RELATION_AUTORUN_MAX_TASKS_PER_TICK", "3"))
        self._relation_field_provider = None       # set by the app; provider() -> RelationField
        self.last_relation_maintenance: Optional[Dict[str, Any]] = None
        self.last_gap_scan: Optional[Dict[str, Any]] = None
        self.relation_maintenance_log = str(rt / "relation_maintenance_log.jsonl")
        self._lock = threading.RLock()
        self._recent: Deque[str] = deque(maxlen=50)
        self._pending_consolidation_reasons: List[str] = []
        self.event_count = 0
        self.state: Dict[str, Any] = {
            "started_at": _now(), "ticks": 0, "interactions": 0,
            "known": 0, "unknown": 0, "provisional": 0, "disputed": 0, "refused": 0,
            "unknown_rate": 0.0, "disputed_rate": 0.0, "repetitions": 0, "feedback_pressure": 0.0,
            "consolidations": 0, "interactions_since_consolidate": 0,
            "last_consolidate_ts": None, "memory_authority": "memory-service (LifeLoop holds none)",
            "source_bleed_failures": 0, "cross_user_leak_failures": 0,
        }

    # -- event stream -------------------------------------------------------
    def _append_event(self, row: Dict[str, Any]) -> str:
        eid = "ev_" + uuid.uuid4().hex[:12]
        rec = {"event_id": eid, "ts": _now(), **row}
        try:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self.event_count += 1
        return eid

    def ingest_event(self, event_type: str, **fields: Any) -> str:
        """Generic rich-event ingestion (memory_action / consolidation / tombstone / compaction /
        vault_training / correction). Returns the event_id."""
        return self._append_event({"event_type": event_type, **fields})

    def record_interaction(self, *, question: str, status: str, user_id: Optional[str] = None,
                           session_id: Optional[str] = None, query_class: Optional[str] = None,
                           source_class: Optional[str] = None, intent: Optional[str] = None,
                           sources: Optional[List[str]] = None, audit_trace_id: Optional[str] = None,
                           stress_percent: Optional[float] = None,
                           answer_head: Optional[str] = None) -> str:
        st = (status or "ERROR").upper()
        secret = _is_secret(question, query_class, source_class)
        q_norm = _norm(question)
        topic = topic_of(question)
        stored_q = "[redacted-secret]" if secret else (question or "")[:200]
        stored_topic = "[secret]" if secret else topic
        repeated = bool(q_norm) and q_norm in self._recent and not secret
        with self._lock:
            self.state["interactions"] += 1
            self.state["interactions_since_consolidate"] += 1
            if st == "KNOWN":
                self.state["known"] += 1
            elif st == "UNKNOWN":
                self.state["unknown"] += 1
            elif st.startswith("PROVISIONAL"):
                self.state["provisional"] += 1
            elif st == "DISPUTED":
                self.state["disputed"] += 1
                self._pending_consolidation_reasons.append("disputed")
            elif st == "REFUSED":
                self.state["refused"] += 1
            tot = max(1, self.state["interactions"])
            self.state["unknown_rate"] = round(self.state["unknown"] / tot, 4)
            self.state["disputed_rate"] = round(self.state["disputed"] / tot, 4)
            if repeated:
                self.state["repetitions"] += 1
            if q_norm:
                self._recent.append(q_norm)
            if source_class == "DISPUTED_OR_UNSAFE" and query_class == "system" and st == "KNOWN":
                pass  # canonical correction (handled by source_policy), not a bleed
        stress_high = bool(stress_percent and float(stress_percent) >= 70)
        eid = self._append_event({
            "event_type": "chat", "user_id": user_id, "session_id": session_id,
            "question": stored_q, "answer_head": ("[redacted]" if secret else (answer_head or "")[:160]),
            "epistemic_status": st, "query_class": query_class, "source_class": source_class,
            "intent": intent, "sources": ([] if secret else (sources or [])[:8]),
            "audit_trace_id": audit_trace_id, "tags": (["secret"] if secret else [])})
        delta = self.pressure.observe(topic=stored_topic, status=st, event_id=eid,
                                      stress_high=stress_high, is_secret=secret)
        # mirror a little of the v1 feedback_pressure for backward-compatible thresholds
        with self._lock:
            self.state["feedback_pressure"] = round(self.state["feedback_pressure"] + max(0.0, delta * 0.0), 3)
        # a REPEATED UNRESOLVED answer (unknown / unverified / needs-source) files an internal
        # research task - never on secrets, memory-first (web needs user permission).
        unresolved = st in ("UNKNOWN", "PROVISIONAL_UNVERIFIED", "ASK_USER_FOR_SOURCE", "NEEDS_MORE_TIME")
        if not secret and unresolved:
            rec = self.pressure.get(stored_topic) or {}
            if (repeated or rec.get("unknown_count", 0) >= 2 or rec.get("provisional_count", 0) >= 2
                    or rec.get("recommended_action") == SCHEDULE_RESEARCH):
                self.tasks.create(topic=stored_topic, question=question,
                                  trigger_event_ids=[eid], priority=1.0 + rec.get("pressure", 0) / 10.0,
                                  allowed_sources=["memory", "vault", "self_state"], is_secret=False)
        return eid

    def record_feedback(self, *, rating: str, user_id: Optional[str] = None,
                        topic: Optional[str] = None, question: Optional[str] = None,
                        audit_trace_id: Optional[str] = None) -> str:
        r = (rating or "").lower()
        tp = topic or (topic_of(question) if question else "feedback")
        eid = self._append_event({"event_type": "feedback", "rating": r, "user_id": user_id,
                                  "audit_trace_id": audit_trace_id, "tags": ["feedback"]})
        delta = self.pressure.feedback(topic=tp, rating=r, event_id=eid)
        with self._lock:
            if delta > 0:                       # negative feedback -> v1 pressure + consolidation hint
                self.state["feedback_pressure"] = round(self.state["feedback_pressure"] + 1.5, 3)
                self._pending_consolidation_reasons.append("correction")
            elif delta < 0:
                self.state["feedback_pressure"] = round(max(0.0, self.state["feedback_pressure"] - 0.5), 3)
        return eid

    def record_event(self, event_type: str, *, topic: Optional[str] = None,
                     success: bool = True, **fields: Any) -> str:
        eid = self.ingest_event(event_type, topic=topic, success=success, **fields)
        if event_type in ("memory_action", "compaction"):
            self._pending_consolidation_reasons.append(event_type)
        if event_type == "correction" and topic:
            self.pressure.correction(topic=topic, event_id=eid)
            self._pending_consolidation_reasons.append("correction")
        return eid

    # -- circulation --------------------------------------------------------
    def should_consolidate(self) -> bool:
        with self._lock:
            return (self.state["interactions_since_consolidate"] >= self.consolidate_every
                    or self.state["feedback_pressure"] >= self.pressure_threshold
                    or self.pressure.total() >= self.pressure_threshold
                    or bool(self._pending_consolidation_reasons))

    def _trigger(self) -> str:
        with self._lock:
            if self._pending_consolidation_reasons:
                return self._pending_consolidation_reasons[0]
            if self.state["interactions_since_consolidate"] >= self.consolidate_every:
                return "interaction_count"
            return "pressure"

    def tick(self, mem_client: Optional[Any] = None, *, learning: Optional[Any] = None) -> Dict[str, Any]:
        with self._lock:
            self.state["ticks"] += 1
        consolidated, result, trigger = False, None, None
        if self.should_consolidate():
            trigger = self._trigger()
            pressure_before = self.pressure.total()
            cand_before = self._candidate_counts(learning)
            if mem_client is not None and hasattr(mem_client, "fce_consolidate"):
                try:
                    result = mem_client.fce_consolidate()
                except Exception as exc:
                    result = {"fce_status": "unavailable", "error": str(exc)}
            fce_status = (result or {}).get("fce_status") if isinstance(result, dict) else None
            success = fce_status not in (None, "unavailable")
            if success:
                self.pressure.relieve(2.0)
            cand_after = self._candidate_counts(learning)
            with self._lock:
                self.state["consolidations"] += 1
                self.state["interactions_since_consolidate"] = 0
                self.state["feedback_pressure"] = max(0.0, self.state["feedback_pressure"] - self.pressure_threshold)
                self.state["last_consolidate_ts"] = _now()
                self._pending_consolidation_reasons.clear()
            self._log_consolidation(trigger, pressure_before, self.pressure.total(), result,
                                    fce_status, cand_before, cand_after)
            consolidated = True
        self.pressure.decay()                       # time-based decay of unattended pressure
        # Cycle 15: scheduled relation maintenance + gap scan (bounded; skipped if memory down).
        relation_cycle = self.run_relation_cycle(mem_client)
        # bounded autonomous memory-only task execution (web/secret/permissioned never run here)
        ran = self.drain_tasks(max_tasks=self.max_tasks_per_tick) if self.autorun_memory_tasks else []
        if self._candidate_consolidator is not None:  # move candidate states (commit/dispute/...)
            try:
                self.last_candidate_decisions = self._candidate_consolidator() or []
            except Exception:
                pass
        self.write_self_state_snapshot(mem_client)
        return {"consolidated": consolidated, "trigger": trigger, "result": result,
                "tasks_run": ran, "relation_maintenance": relation_cycle.get("maintenance"),
                "relation_gaps": len(relation_cycle.get("gaps", [])),
                "relation_cycle": relation_cycle, "self_state": self.snapshot()}

    @staticmethod
    def _candidate_counts(learning: Any) -> Any:
        if learning is None:
            return {"candidates": None, "disputed": None}
        try:
            return {"candidates": len(learning.list_candidates()),
                    "disputed": len(learning.list_disputed())}
        except Exception:
            return {"candidates": None, "disputed": None}

    def _log_consolidation(self, trigger: Any, p_before: Any, p_after: Any, result: Any, fce_status: Any, cand_before: Any, cand_after: Any) -> None:
        rec = {"ts": _now(), "trigger": trigger, "pressure_before": p_before,
               "pressure_after": p_after, "result": result, "fce_status": fce_status,
               "candidates_before": cand_before.get("candidates"),
               "candidates_after": cand_after.get("candidates"),
               "disputed_before": cand_before.get("disputed"),
               "disputed_after": cand_after.get("disputed")}
        try:
            with self.consolidation_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # -- autonomous memory-only task execution (Cycle 7) --------------------
    def set_task_runner(self, runner: Any) -> None:
        """runner(task) -> result dict; runs a MEMORY-ONLY task through the canonical research
        loop and stores its result as a candidate (never truth). Set by the app."""
        self._task_runner = runner

    def set_candidate_hooks(self, *, consolidator: Optional[Any]=None, status_provider: Optional[Any]=None) -> None:
        """consolidator() -> list of decisions (the ONLY path that moves candidate state);
        status_provider() -> dict of candidate counts/last-decision for status. Set by the app."""
        if consolidator is not None:
            self._candidate_consolidator = consolidator
        if status_provider is not None:
            self._candidate_status_provider = status_provider

    def set_relation_field_provider(self, provider: Any) -> None:
        """provider() -> RelationField (built from the canonical namespace). Set by the app so the
        tick can run scheduled relation maintenance + gap scan without holding a parallel store."""
        self._relation_field_provider = provider

    def _relation_field(self) -> Optional[Any]:
        if self._relation_field_provider is None:
            return None
        try:
            return self._relation_field_provider()
        except Exception:
            return None

    def _memory_service_ok(self, mem_client: Optional[Any]) -> bool:
        """Cycle 14 guard: if the memory-service is down, maintenance does NOT run (no fabrication)."""
        if mem_client is not None and hasattr(mem_client, "health"):
            try:
                return bool((mem_client.health() or {}).get("_reachable"))
            except Exception:
                return False
        return True

    def run_relation_cycle(self, mem_client: Optional[Any] = None) -> Dict[str, Any]:
        """Scheduled relation maintenance + gap scan for this tick (bounded). Skipped entirely if
        the memory-service is down. Never answers the user, never commits, never deletes."""
        out: Dict[str, Any] = {"maintenance": None, "gaps": [], "skipped": None}
        if self._relation_field_provider is None:
            out["skipped"] = "no relation field provider"
            return out
        if not self._memory_service_ok(mem_client):
            out["skipped"] = "memory-service down (maintenance skipped, no fabrication)"
            return out
        field = self._relation_field()
        if field is None:
            out["skipped"] = "relation field unavailable"
            return out
        ticks = self.state["ticks"]
        if self.relation_maintenance_enabled and ticks % max(1, self.maintenance_every_ticks) == 0:
            try:
                from gateway.relation_maintenance import run_relation_decay_maintenance
                rep = run_relation_decay_maintenance(field, log_path=self.relation_maintenance_log)
                self.last_relation_maintenance = {
                    "maintenance_id": rep["maintenance_id"], "timestamp": rep["timestamp"],
                    "relations_scanned": rep["relations_scanned"],
                    "relations_decayed": rep["relations_decayed"],
                    "canonical_resisted_decay": rep["canonical_resisted_decay"],
                    "disputed_decayed": rep["disputed_decayed"],
                    "weak_relations_flagged": len(rep["weak_relations_flagged"]),
                    "central_weak_nodes": rep["central_weak_nodes"][:5],
                    "recommended_tasks": len(rep["recommended_tasks"])}
                out["maintenance"] = self.last_relation_maintenance
            except Exception as exc:
                out["maintenance_error"] = str(exc)
        if ticks % max(1, self.gap_scan_every_ticks) == 0:
            try:
                from gateway.relation_field import RelationGapScanner
                gaps = RelationGapScanner(field, tasks=self.tasks).scan()
                out["gaps"] = gaps
                self.last_gap_scan = {"ts": _now(), "gaps_found": len(gaps),
                                      "tasks_created": sum(1 for g in gaps if g.get("task_id"))}
            except Exception as exc:
                out["gap_scan_error"] = str(exc)
        return out

    @staticmethod
    def _is_memory_only(task: Dict[str, Any]) -> bool:
        allowed = set(task.get("allowed_sources") or [])
        return ("web" not in allowed and not task.get("requires_user_permission")
                and task.get("topic") != "[secret]" and "secret" not in (task.get("topic") or ""))

    def drain_tasks(self, max_tasks: int = 3) -> List[Dict[str, Any]]:
        """Auto-run a few SAFE memory-only tasks. Web/secret/permissioned tasks are never run
        here. Each result is logged and stored as a candidate by the runner (never committed)."""
        from gateway.research_tasks import PENDING, RUNNING, DONE, FAILED, BLOCKED_NEEDS_PERMISSION
        if self._task_runner is None:
            return []
        ran: List[Dict[str, Any]] = []
        for task in sorted(self.tasks.pending(), key=lambda t: -t.get("priority", 0)):
            if len(ran) >= max_tasks:
                break
            if task.get("status") != PENDING or not self._is_memory_only(task):
                continue                       # blocked web / needs-permission / secret -> skip
            tid = task["task_id"]
            self.tasks.set_status(tid, RUNNING)
            self.last_auto_run_task = tid
            try:
                result = self._task_runner(task) or {}
            except Exception as exc:
                result = {"epistemic_status": "ERROR", "error": str(exc)}
            status = result.get("epistemic_status")
            disputed = status == "DISPUTED"
            success = status in ("KNOWN", "PROVISIONAL", "PROVISIONAL_UNVERIFIED", "ACTION_DONE")
            failed = status in (None, "ERROR")
            self.record_task_result(task, result)
            self.pressure.task_outcome(topic=task.get("topic", ""), success=success and not failed,
                                       disputed=disputed)
            if failed:
                # repeated failure on a topic -> stop looping, ask the user
                rec = self.pressure.get(task.get("topic", "")) or {}
                if rec.get("fail_count", 0) >= 2:
                    self.tasks.set_status(tid, BLOCKED_NEEDS_PERMISSION,
                                          result={"reason": "repeated failure - needs user input"})
                else:
                    self.tasks.set_status(tid, FAILED, result=result)
            else:
                self.tasks.set_status(tid, DONE, result=result)
            ran.append({"task_id": tid, "status": status})
        return ran

    def record_task_result(self, task: Dict[str, Any], result: Dict[str, Any]) -> None:
        rec = {
            "task_id": task.get("task_id"), "topic": task.get("topic"),
            "question": task.get("question"), "sources_used": result.get("sources_used", []),
            "answer_summary": (result.get("answer_summary") or "")[:300],
            "epistemic_status": result.get("epistemic_status"), "confidence": result.get("confidence"),
            "stored_as": result.get("stored_as", "candidate"), "candidate_id": result.get("candidate_id"),
            "audit_trace_id": result.get("audit_trace_id"),
            "created_at": _now()}
        self.last_task_result = rec
        for path, payload in ((self.task_results_path, rec),
                              (self.task_exec_log, {"ts": _now(), "task_id": rec["task_id"],
                                                    "epistemic_status": rec["epistemic_status"],
                                                    "stored_as": rec["stored_as"]})):
            try:
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except OSError:
                pass
        self.ingest_event("research_task_run", task_id=rec["task_id"],
                          epistemic_status=rec["epistemic_status"], stored_as=rec["stored_as"])

    def mark_resolved(self, topic: str) -> None:
        """Operator marks a topic resolved -> relieve its pressure and cancel its open tasks."""
        self.pressure.relieve_topic(topic, amount=999.0)
        for t in self.tasks.pending():
            if t.get("topic") == topic:
                self.tasks.cancel(t["task_id"])

    # -- self-state temporal snapshots --------------------------------------
    def write_self_state_snapshot(self, mem_client: Optional[Any] = None) -> Dict[str, Any]:
        s = self.snapshot()
        active_vault = tombstoned_vault = None
        read_mode = getattr(mem_client, "read_consistency_mode", None)
        if mem_client is not None and hasattr(mem_client, "vault_fact_count"):
            try:
                vc = mem_client.vault_fact_count(os.environ.get("BYON_VAULT_OWNER", "lucian"))
                active_vault, tombstoned_vault = vc.get("active"), vc.get("tombstoned")
            except Exception:
                pass
        snap = {
            "ts": _now(), "tick": s["ticks"],
            "known_count": s["known"], "unknown_count": s["unknown"],
            "provisional_count": s["provisional"], "disputed_count": s["disputed"],
            "unknown_rate": s["unknown_rate"], "disputed_rate": s["disputed_rate"],
            "pressure_total": self.pressure.total(),
            "top_pressure_topics": [t["topic"] for t in self.pressure.top(5)],
            "active_research_tasks": len(self.tasks.pending()),
            "pending_consolidations": len(self._pending_consolidation_reasons),
            "active_vault_facts": active_vault, "tombstoned_vault_facts": tombstoned_vault,
            "read_consistency_mode": read_mode,
            "last_consolidation": s["last_consolidate_ts"],
            "consolidation_count": s["consolidations"],
            "memory_growth_delta": None,
            "source_bleed_failures": s["source_bleed_failures"],
            "cross_user_leak_failures": s["cross_user_leak_failures"],
            "relation_maintenance": self.last_relation_maintenance,
            "relation_gap_scan": self.last_gap_scan,
        }
        try:
            with self.snapshots_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(snap, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return snap

    def recent_snapshots(self, n: int = 10) -> List[Dict[str, Any]]:
        if not self.snapshots_path.exists():
            return []
        try:
            lines = self.snapshots_path.read_text(encoding="utf-8").splitlines()[-n:]
            return [json.loads(x) for x in lines if x.strip()]
        except (OSError, json.JSONDecodeError):
            return []

    # -- status -------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            s = dict(self.state)
        s["recent_unique_questions"] = len(set(self._recent))
        return s

    def status_v2(self, mem_client: Optional[Any] = None) -> Dict[str, Any]:
        s = self.snapshot()
        read_mode = getattr(mem_client, "read_consistency_mode", None)
        active_vault = tombstoned_vault = None
        if mem_client is not None and hasattr(mem_client, "vault_fact_count"):
            try:
                vc = mem_client.vault_fact_count(os.environ.get("BYON_VAULT_OWNER", "lucian"))
                active_vault, tombstoned_vault = vc.get("active"), vc.get("tombstoned")
            except Exception:
                pass
        return {
            "enabled": True, "version": VERSION,
            "last_tick": s["last_consolidate_ts"], "ticks": s["ticks"],
            "event_count": self.event_count,
            "pressure_total": self.pressure.total(),
            "top_pressure_topics": self.pressure.top(5),
            "pending_research_tasks": self.tasks.pending(),
            "research_task_counts": self.tasks.counts(),
            "blocked_web_tasks": [t for t in self.tasks.list() if t.get("status") == "blocked_needs_permission"],
            "last_auto_run_task": self.last_auto_run_task,
            "last_task_result": self.last_task_result,
            "last_candidate_decisions": self.last_candidate_decisions[-10:],
            "candidates": (self._candidate_status_provider() if self._candidate_status_provider else {}),
            "last_consolidation": s["last_consolidate_ts"],
            "consolidation_count": s["consolidations"],
            "unknown_rate": s["unknown_rate"], "disputed_rate": s["disputed_rate"],
            "source_bleed_failures": s["source_bleed_failures"],
            "memory_service_read_consistency_mode": read_mode,
            "active_vault_facts": active_vault, "tombstoned_vault_facts": tombstoned_vault,
            "answers_user_directly": False, "is_truth_authority": False,
            "memory_authority": s["memory_authority"],
        }
