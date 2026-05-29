# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""MemoryServiceBackend - the canonical BYON backend for the epistemic search runtime.

Routes everything through the real memory-service (FAISS + FCE-M + trust tiers) via the
EpistemicSearch loop. Per-user isolation maps BYON user_id → memory-service thread_id, so a
user sees their own facts plus system-scope canonical facts (thread_id=None). Teaching a fact
commits it (USER_PREFERENCE trust). Questions run the full epistemic search.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from gateway.byon_backend import BYONResult
from gateway.continuous_learning import ContinuousLearning
from gateway.epistemic_search import ClaudeHypothesisProvider, EpistemicSearch, is_secret_query
from gateway.expression_learning import ExpressionLearning
from gateway.memory_service_client import MemoryServiceClient
from gateway.recent_write_buffer import RecentWriteBuffer
from gateway import fact_extractor_bridge as feb
from gateway import web_search as ws

_CANONICAL = [
    ("byon operational level", "BYON is allowed to claim Level 2; Level 3 is explicitly not declared."),
    ("byon level 3", "BYON does not declare Level 3 (FULL_LEVEL3_NOT_DECLARED)."),
    ("byon epistemic contract", "No model may assert from prior. An answer may be asserted only "
     "if anchored in valid committed memory with provenance. Otherwise UNKNOWN."),
]
_seeded = False


def _parse_teach(message: str) -> Any:
    m = message.strip()
    mm = re.match(r"(?i)^(?:please\s+)?(?:remember(?:\s+that)?|note(?:\s+that)?|fyi[:,]?)\s+(.+)$", m)
    if mm:
        body = mm.group(1).strip()
        kv = re.match(r"(?i)^(.+?)\s+(?:is|are|=|:)\s+(.+)$", body)
        return (kv.group(1).strip(), kv.group(2).strip().rstrip(".")) if kv else (body, body)
    if not m.endswith("?"):
        kv = re.match(r"(?i)^(?:my|the)?\s*(.+?)\s+(?:is|are|=|:)\s+(.+)$", m)
        if kv and len(kv.group(1)) <= 60:
            return kv.group(1).strip(), kv.group(2).strip().rstrip(".")
    return None


class MemoryServiceBackend:
    def __init__(self, memory_url: str='http://127.0.0.1:8000', *, mem_client: Optional[Any]=None, web_provider: Optional[Any]=None, claude_provider: Optional[Any]=None) -> None:
        self.memory_url = memory_url
        # Production wraps the canonical client in the read-consistent, tombstone-aware layer
        # (Cycle 5). Tests may inject a raw client.
        if mem_client is not None:
            self.mem = mem_client
        else:
            from gateway.consistent_client import ConsistentMemoryClient
            self.mem = ConsistentMemoryClient(MemoryServiceClient(memory_url))
        self.web = web_provider if web_provider is not None else ws.get_provider()
        self.claude = claude_provider if claude_provider is not None else ClaudeHypothesisProvider()
        self.search = EpistemicSearch()
        self.recent_buffer = RecentWriteBuffer()   # Cycle 4: immediate recall before FAISS catches up
        self.default_allow_web = os.environ.get("BYON_WEB_SEARCH_ENABLED", "false").strip().lower() in (
            "1", "true", "yes", "on")
        self._seed_canonical()

    def _seed_canonical(self) -> None:
        global _seeded
        if _seeded:
            return
        try:
            for ent, fact in _CANONICAL:
                self.mem.store_fact(fact, source="system:canonical", tags=["byon", "canonical", ent],
                                    thread_id=None, trust="VERIFIED_PROJECT_FACT")
            _seeded = True
        except Exception:
            pass  # seeding is best-effort; the search still runs

    def memory_service_up(self) -> bool:
        """Cycle 14 (S6): is the canonical memory-service reachable right now? Used to fail safely
        (ERROR/REFUSED) instead of fabricating or falling back to Claude / a local backend."""
        try:
            return bool((self.mem.health() or {}).get("_reachable"))
        except Exception:
            return False

    def status(self) -> Dict[str, Any]:
        h = self.mem.health()
        up = bool(h.get("_reachable"))
        return {
            "backend": "memory-service",
            "memory_service_up": up,
            "memory_service": {"reachable": up, "version": h.get("version")},
            "web": {"provider": getattr(self.web, "name", "disabled"),
                    "available": getattr(self.web, "available", False),
                    "enabled": self.default_allow_web},
            "claude": {"language_only": True, "available": getattr(self.claude, "available", False)},
            "dcortex": {"source": "canonical memory-service FAISS + FCE-M", "version": "memory-service"},
            "fcem": {"runtime_proven": up},
        }

    @staticmethod
    def _memory_down_result(research_trace_id: Optional[str]) -> Dict[str, Any]:
        """Cycle 14 (S6): the safe degraded response when the memory-service is down. No fabricated
        answer, no Claude fallback that bypasses memory, no LocalBYONBackend in REAL."""
        return {"epistemic_status": "ERROR", "research_status": "error", "answer": "",
                "grounded": False, "confidence": 0.0, "sources_searched": [], "web_results": [],
                "claude_hypothesis": None, "stress_percent": 0.0, "phase": "error", "clock": {},
                "memory_service_up": False,
                "synthesis": {"epistemic_verdict": "ERROR", "reason": "memory_service_down",
                              "note": "canonical memory-service unreachable; refusing to answer "
                                      "(no fabrication, no Claude/local fallback)"},
                "research_trace_id": research_trace_id or "memory_service_down", "can_extend": False}

    def _learning(self, namespace_dir: Any, user_id: str) -> Any:
        return ContinuousLearning(namespace_dir, self.mem, thread_id=user_id)

    def _learn_from_message(self, message: str, user_id: str, learning: Any, channel: str='web') -> Any:
        """Canonical learning from a user message: route through the REAL FactExtractor
        (LLM extract → classify trust → store via memory-service). Falls back to a
        non-canonical heuristic ONLY if the canonical extractor is unavailable; anything
        the fallback stores is tagged `non_canonical_fallback`."""
        if is_secret_query(message):
            return {"facts": [], "canonical": True, "skipped": "secret"}
        is_question = message.strip().endswith("?")
        if feb.available():
            out = feb.extract_and_store(message, thread_id=user_id, channel=channel,
                                        memory_url=self.memory_url)
            # Cycle 4: buffer the just-written FACTS (never a question) so they are recallable
            # before FAISS indexes them. A question is not a fact and must not be recalled back.
            if not is_question:
                for f in out.get("facts", []):
                    txt = " ".join(str(f.get(k, "")) for k in ("subject", "predicate", "object")).strip()
                    if txt:
                        self.recent_buffer.add(user_id, txt)
            learning.record_event("interaction", canonical=bool(out.get("canonical")),
                                  facts=len(out.get("facts", [])), trust_tiers=out.get("trust_tiers"))
            return {"facts": out.get("facts", []), "canonical": bool(out.get("canonical")),
                    "trust_tiers": out.get("trust_tiers", {})}
        # non-canonical emergency fallback (clearly tagged)
        teach = _parse_teach(message)
        if teach and not message.strip().endswith("?"):
            entity, value = teach
            self.mem.store_fact(message.strip(), source=f"non_canonical_fallback:user:{user_id}",
                                tags=["user", "non_canonical_fallback", entity],
                                thread_id=user_id, trust="USER_PREFERENCE")
            self.recent_buffer.add(user_id, message.strip())   # Cycle 4: immediate recall
            learning.record_event("interaction", canonical=False, fallback=True,
                                  facts=[{"subject": entity, "object": value}])
            return {"facts": [{"subject": entity, "predicate": "is", "object": value}],
                    "canonical": False}
        learning.record_event("interaction", canonical=False, facts=0)
        return {"facts": [], "canonical": False}

    # -- full research (drives /v1/research) --------------------------------
    def research(self, *, user_id: str, session_id: str, question: str, namespace_dir: Any, allow_web: Optional[bool]=None, allow_claude: bool=True, action: str='start', research_trace_id: Optional[str]=None, acquisition_context: Optional[Dict[str, Any]]=None) -> Any:
        # Cycle 14 (S6): if the canonical memory-service is down, fail safe BEFORE any Claude/learning
        # path. The Gateway never fabricates and never falls back to Claude/local when memory is down.
        if not self.memory_service_up():
            return self._memory_down_result(research_trace_id)
        learning = self._learning(namespace_dir, user_id)
        expr = ExpressionLearning(self.mem, namespace_dir=str(namespace_dir) if namespace_dir else None)
        # CANONICAL learning side-effect: every non-secret user message goes through the
        # real FactExtractor before the search loop (Phase 2).
        is_question = question.strip().endswith("?")
        # Gate 10: a pure style/expression instruction is learned as USER_PREFERENCE (not a world
        # fact) and acknowledged - it tunes delivery, never truth.
        if action == "start":
            pref = expr.store_preference(user_id, question)
            if pref and not is_question:
                kinds = ", ".join(pref["kinds"])
                return {"epistemic_status": "ACTION_DONE", "research_status": "done",
                        "answer": f"Am notat preferinta de exprimare ({kinds}). O aplic la raspunsuri, "
                                  f"fara sa modific statusul epistemic sau sursele.",
                        "grounded": True, "confidence": 0.9,
                        "sources_searched": ["style:user_preference"], "web_results": [],
                        "claude_hypothesis": None, "stress_percent": 0.0, "phase": "done", "clock": {},
                        "synthesis": {"epistemic_verdict": "ACTION_DONE", "intent": "EXPRESSION_PREFERENCE",
                                      "sources": ["style:user_preference"]},
                        "research_trace_id": research_trace_id or "style", "can_extend": False,
                        "expression_preference": pref}
        learned = {"facts": []}
        if action == "start":
            learned = self._learn_from_message(question, user_id, learning)
        # If the message taught facts and is not a question, acknowledge what was learned.
        if action == "start" and learned.get("facts") and not is_question:
            facts = learned["facts"]
            ack = "; ".join(f"{f.get('subject','')} {str(f.get('predicate','')).replace('_',' ')} "
                            f"{f.get('object','')}".strip() for f in facts[:5])
            tag = "canonical FactExtractor" if learned.get("canonical") else "non-canonical fallback"
            return {"epistemic_status": "KNOWN", "research_status": "done",
                    "answer": f"Learned ({tag}): {ack}", "grounded": True, "confidence": 0.85,
                    "sources_searched": ["fact-extractor", "memory"], "web_results": [],
                    "claude_hypothesis": None, "stress_percent": 0.0, "phase": "done", "clock": {},
                    "synthesis": {"epistemic_verdict": "KNOWN", "memory_view": "stored via FactExtractor",
                                  "trust_tiers": learned.get("trust_tiers", {})},
                    "research_trace_id": research_trace_id or "learn", "can_extend": True,
                    "learned": learned}
        aw = self.default_allow_web if allow_web is None else allow_web
        out = self.search.run(question=question, user_id=user_id, session_id=session_id,
                              namespace_dir=namespace_dir, mem_client=self.mem, learning=learning,
                              web_provider=self.web, claude_provider=self.claude,
                              allow_web=aw, allow_claude=allow_claude, action=action,
                              research_trace_id=research_trace_id, recent_buffer=self.recent_buffer,
                              acquisition_context=acquisition_context)
        # Gate 10: re-phrase the DELIVERY per learned style - status & sources are left untouched.
        try:
            syn = out.get("synthesis") or {}
            srcs = syn.get("sources") or out.get("sources_searched") or []
            out["answer"] = expr.apply(user_id, session_id, out.get("answer", ""),
                                       out.get("epistemic_status"), srcs)
        except Exception:
            pass  # styling is best-effort; never block or alter a truthful answer
        try:   # Cycle 4: surface indexing-in-progress so callers know reads may be churning
            from gateway.write_lock import VaultTrainingLock
            if VaultTrainingLock().status().get("indexing_in_progress"):
                out["indexing_in_progress"] = True
        except Exception:
            pass
        return out

    # -- BYONBackend.chat ----------------------------------------------------
    def chat(self, *, user_id: str, session_id: str, channel: str, message: str, namespace_dir: Any) -> Any:
        # chat delegates to the canonical research loop (which also learns via FactExtractor)
        out = self.research(user_id=user_id, session_id=session_id, question=message,
                            namespace_dir=namespace_dir, action="start")
        syn = out.get("synthesis") or {}
        return BYONResult(
            answer=out.get("answer", ""), epistemic_status=out.get("epistemic_status", "UNKNOWN"),
            grounded=bool(out.get("grounded")), final_audit_passed=True,
            has_valid_memory=bool(out.get("memory_hits")),
            sources=syn.get("sources", []) or out.get("sources_searched", []),
            memory_written=bool(syn.get("candidate")),
            dcortex={"verdict": out.get("epistemic_status"), "unknown_gate": out.get("epistemic_status") == "UNKNOWN",
                     "contradiction_status": "disputed" if out.get("epistemic_status") == "DISPUTED" else "none"},
            fcem={"runtime_proven": True, "advisory_nonempty": bool(out.get("web_results")),
                  "pressure_max": out.get("stress_percent")})

    def memory_status(self, *, user_id: str, namespace_dir: Any) -> Any:
        # Cycle 14 (S6): when the memory-service is down, report it plainly without touching the
        # (unreachable) stats/substrate endpoints.
        if not self.memory_service_up():
            return {"available": False, "memory_service_up": False,
                    "note": "canonical memory-service unreachable", **self.status()}
        learning = self._learning(namespace_dir, user_id)
        return {"available": True, "candidates": learning.list_candidates(),
                "committed": learning.list_committed(), "disputed": learning.list_disputed(),
                "memory_service_stats": self.mem.stats(), "substrate": self.substrate_status(),
                **self.status()}

    def substrate_status(self, *, report_dir: str = "runtime/training") -> Dict[str, Any]:
        """Cycle 4: substrate health - vault report coherence, write-lock / indexing-in-progress,
        recent-write buffer size, and an orphan-writer warning."""
        from pathlib import Path as _P
        import json as _json
        from gateway.write_lock import VaultTrainingLock
        vault: Dict[str, Any] = {"present": False}
        try:
            p = _P(report_dir) / "vault_train_report.json"
            if p.exists():
                r = _json.loads(p.read_text(encoding="utf-8"))
                vault = {"present": True, "complete": r.get("complete"), "partial": r.get("partial"),
                         "stale": r.get("stale"), "files_scanned": r.get("files_scanned"),
                         "files_indexed": r.get("files_indexed"), "eligible_files": r.get("eligible_files"),
                         "errors": r.get("errors"), "errors_by_type": r.get("errors_by_type"),
                         "vault_facts_in_memory": r.get("vault_facts_in_memory"),
                         "manifest_active_chunks": r.get("manifest_active_chunks")}
        except Exception:
            pass
        lock = VaultTrainingLock().status()
        # Cycle 5: read-consistency mode + active vs tombstoned vault facts
        read_mode = getattr(self.mem, "read_consistency_mode", "direct")
        engine_consistency = (self.mem.engine_consistency_status()
                              if hasattr(self.mem, "engine_consistency_status") else {})
        tomb_counts = self.mem.tombstone_counts() if hasattr(self.mem, "tombstone_counts") else {}
        active_vault = tombstoned_vault = None
        try:
            if hasattr(self.mem, "vault_fact_count"):
                vc = self.mem.vault_fact_count(os.environ.get("BYON_VAULT_OWNER", "lucian"))
                active_vault, tombstoned_vault = vc.get("active"), vc.get("tombstoned")
        except Exception:
            pass
        return {
            "memory_service_reachable": bool((self.mem.health() or {}).get("_reachable")),
            "read_consistency_mode": read_mode,
            "engine_consistency": engine_consistency,
            "vault_report": vault,
            "active_vault_facts": active_vault, "tombstoned_vault_facts": tombstoned_vault,
            "tombstones": tomb_counts,
            "indexing_in_progress": bool(lock.get("indexing_in_progress")),
            "active_writer_pid": lock.get("pid") if lock.get("indexing_in_progress") else None,
            "lock": lock,
            "orphan_writer_warning": bool(lock.get("locked") and lock.get("stale")),
            "recent_write_buffer_count": self.recent_buffer.count(),
        }

    def consolidate(self, *, user_id: str, namespace_dir: Any) -> Any:
        return self._learning(namespace_dir, user_id).consolidate()

    def apply_feedback(self, *, user_id: str, namespace_dir: Any, rating: str, value: Optional[str]=None, note: Optional[str]=None, audit_trace_id: Optional[str]=None) -> Any:
        """Feedback is a learning signal (Phase 9): reinforce / dispute / queue, and raise
        FCE-M pressure via a receipt (success/failed)."""
        learning = self._learning(namespace_dir, user_id)
        target = (value or note or "").strip()
        action = "logged"
        if rating in ("wrong", "false"):
            if target:
                learning.dispute(target, reason=f"feedback:{rating}")
            action = "disputed"
            self.mem.fce_assimilate_receipt(audit_trace_id or "feedback", "failed", summary=note)
        elif rating in ("correct", "right", "important", "remember_this", "partially_correct"):
            if target:
                learning.reinforce(target, delta=(2 if rating == "important" else 1))
            action = "reinforced"
            self.mem.fce_assimilate_receipt(audit_trace_id or "feedback", "success", summary=note)
        elif rating == "do_not_remember" and target:
            learning.dispute(target, reason="do_not_remember")
            action = "removed_from_candidates"
        elif rating == "verify_again":
            action = "queued_for_reverification"
        # a rejected answer may carry a STYLE complaint ("too long", "prea abstract") -> update
        # style memory (never touches the underlying fact's correctness).
        style_pref = None
        if rating in ("wrong", "false", "partially_correct", "do_not_remember") or note:
            try:
                style_pref = ExpressionLearning(self.mem,
                    namespace_dir=str(namespace_dir) if namespace_dir else None
                ).record_rejection(user_id, note or value or "")
            except Exception:
                style_pref = None
        learning.record_event("feedback", rating=rating, target=target[:80], action=action,
                              about_trace=audit_trace_id, style_pref=bool(style_pref))
        return {"ok": True, "rating": rating, "action": action,
                "style_preference": style_pref}

    def forget(self, *, user_id: str, namespace_dir: Any) -> Any:
        cleared = []
        for name in ("events.jsonl", "research_traces.jsonl", "memory_candidates.jsonl",
                     "facts.jsonl", "archive.jsonl"):
            p = Path(namespace_dir) / name
            if p.exists():
                p.unlink()
                cleared.append(name)
        return {"forgotten": True, "cleared": cleared,
                "note": "per-user lifecycle ledgers cleared; canonical system facts retained"}
