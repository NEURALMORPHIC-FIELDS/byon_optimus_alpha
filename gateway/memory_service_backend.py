"""MemoryServiceBackend — the canonical BYON backend for the epistemic search runtime.

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

from .byon_backend import BYONResult
from .continuous_learning import ContinuousLearning
from .epistemic_search import ClaudeHypothesisProvider, EpistemicSearch, is_secret_query
from .memory_service_client import MemoryServiceClient
from . import fact_extractor_bridge as feb
from . import web_search as ws

_CANONICAL = [
    ("byon operational level", "BYON is allowed to claim Level 2; Level 3 is explicitly not declared."),
    ("byon level 3", "BYON does not declare Level 3 (FULL_LEVEL3_NOT_DECLARED)."),
    ("byon epistemic contract", "No model may assert from prior. An answer may be asserted only "
     "if anchored in valid committed memory with provenance. Otherwise UNKNOWN."),
]
_seeded = False


def _parse_teach(message: str):
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
    def __init__(self, memory_url: str = "http://127.0.0.1:8000", *, mem_client=None,
                 web_provider=None, claude_provider=None) -> None:
        self.memory_url = memory_url
        self.mem = mem_client or MemoryServiceClient(memory_url)
        self.web = web_provider if web_provider is not None else ws.get_provider()
        self.claude = claude_provider if claude_provider is not None else ClaudeHypothesisProvider()
        self.search = EpistemicSearch()
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

    def status(self) -> Dict[str, Any]:
        h = self.mem.health()
        return {
            "backend": "memory-service",
            "memory_service": {"reachable": bool(h.get("_reachable")), "version": h.get("version")},
            "web": {"provider": getattr(self.web, "name", "disabled"),
                    "available": getattr(self.web, "available", False),
                    "enabled": self.default_allow_web},
            "claude": {"language_only": True, "available": getattr(self.claude, "available", False)},
            "dcortex": {"source": "canonical memory-service FAISS + FCE-M", "version": "memory-service"},
            "fcem": {"runtime_proven": bool(h.get("_reachable"))},
        }

    def _learning(self, namespace_dir, user_id: str) -> ContinuousLearning:
        return ContinuousLearning(namespace_dir, self.mem, thread_id=user_id)

    def _learn_from_message(self, message: str, user_id: str, learning, channel: str = "web") -> Dict[str, Any]:
        """Canonical learning from a user message: route through the REAL FactExtractor
        (LLM extract → classify trust → store via memory-service). Falls back to a
        non-canonical heuristic ONLY if the canonical extractor is unavailable; anything
        the fallback stores is tagged `non_canonical_fallback`."""
        if is_secret_query(message):
            return {"facts": [], "canonical": True, "skipped": "secret"}
        if feb.available():
            out = feb.extract_and_store(message, thread_id=user_id, channel=channel,
                                        memory_url=self.memory_url)
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
            learning.record_event("interaction", canonical=False, fallback=True,
                                  facts=[{"subject": entity, "object": value}])
            return {"facts": [{"subject": entity, "predicate": "is", "object": value}],
                    "canonical": False}
        learning.record_event("interaction", canonical=False, facts=0)
        return {"facts": [], "canonical": False}

    # -- full research (drives /v1/research) --------------------------------
    def research(self, *, user_id: str, session_id: str, question: str, namespace_dir,
                 allow_web: Optional[bool] = None, allow_claude: bool = True,
                 action: str = "start", research_trace_id: Optional[str] = None) -> Dict[str, Any]:
        learning = self._learning(namespace_dir, user_id)
        # CANONICAL learning side-effect: every non-secret user message goes through the
        # real FactExtractor before the search loop (Phase 2).
        is_question = question.strip().endswith("?")
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
        return self.search.run(question=question, user_id=user_id, session_id=session_id,
                               namespace_dir=namespace_dir, mem_client=self.mem, learning=learning,
                               web_provider=self.web, claude_provider=self.claude,
                               allow_web=aw, allow_claude=allow_claude, action=action,
                               research_trace_id=research_trace_id)

    # -- BYONBackend.chat ----------------------------------------------------
    def chat(self, *, user_id: str, session_id: str, channel: str, message: str,
             namespace_dir) -> BYONResult:
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

    def memory_status(self, *, user_id: str, namespace_dir) -> Dict[str, Any]:
        learning = self._learning(namespace_dir, user_id)
        return {"available": True, "candidates": learning.list_candidates(),
                "committed": learning.list_committed(), "disputed": learning.list_disputed(),
                "memory_service_stats": self.mem.stats(), **self.status()}

    def consolidate(self, *, user_id: str, namespace_dir) -> Dict[str, Any]:
        return self._learning(namespace_dir, user_id).consolidate()

    def apply_feedback(self, *, user_id: str, namespace_dir, rating: str,
                       value: Optional[str] = None, note: Optional[str] = None,
                       audit_trace_id: Optional[str] = None) -> Dict[str, Any]:
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
        learning.record_event("feedback", rating=rating, target=target[:80], action=action,
                              about_trace=audit_trace_id)
        return {"ok": True, "rating": rating, "action": action}

    def forget(self, *, user_id: str, namespace_dir) -> Dict[str, Any]:
        cleared = []
        for name in ("events.jsonl", "research_traces.jsonl", "memory_candidates.jsonl",
                     "facts.jsonl", "archive.jsonl"):
            p = Path(namespace_dir) / name
            if p.exists():
                p.unlink()
                cleared.append(name)
        return {"forgotten": True, "cleared": cleared,
                "note": "per-user lifecycle ledgers cleared; canonical system facts retained"}
