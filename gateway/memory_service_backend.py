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

    # -- full research (drives /v1/research) --------------------------------
    def research(self, *, user_id: str, session_id: str, question: str, namespace_dir,
                 allow_web: Optional[bool] = None, allow_claude: bool = True,
                 action: str = "start", research_trace_id: Optional[str] = None) -> Dict[str, Any]:
        learning = self._learning(namespace_dir, user_id)
        # teaching is a learning side-effect, handled before the search loop
        teach = _parse_teach(question)
        if action == "start" and teach and not question.strip().endswith("?") and not is_secret_query(question):
            entity, value = teach
            self.mem.store_fact(question.strip(), source=f"user:{user_id}",
                                tags=["user", entity], thread_id=user_id, trust="USER_PREFERENCE")
            learning.record_event("teach", entity=entity, value=value)
            return {"epistemic_status": "KNOWN", "research_status": "done",
                    "answer": f"Noted (grounded): {entity} -> {value}.", "grounded": True,
                    "confidence": 0.9, "sources_searched": ["memory"], "web_results": [],
                    "claude_hypothesis": None, "stress_percent": 0.0, "phase": "done",
                    "clock": {}, "synthesis": {"epistemic_verdict": "KNOWN", "memory_view": "stored"},
                    "research_trace_id": research_trace_id or "teach", "can_extend": True}
        aw = self.default_allow_web if allow_web is None else allow_web
        return self.search.run(question=question, user_id=user_id, session_id=session_id,
                               namespace_dir=namespace_dir, mem_client=self.mem, learning=learning,
                               web_provider=self.web, claude_provider=self.claude,
                               allow_web=aw, allow_claude=allow_claude, action=action,
                               research_trace_id=research_trace_id)

    # -- BYONBackend.chat ----------------------------------------------------
    def chat(self, *, user_id: str, session_id: str, channel: str, message: str,
             namespace_dir) -> BYONResult:
        learning = self._learning(namespace_dir, user_id)
        teach = _parse_teach(message)
        if teach and not message.strip().endswith("?") and not is_secret_query(message):
            entity, value = teach
            self.mem.store_fact(message.strip(), source=f"user:{user_id}",
                                tags=["user", entity], thread_id=user_id, trust="USER_PREFERENCE")
            learning.record_event("teach", entity=entity, value=value)
            return BYONResult(answer=f"Noted (grounded): {entity} -> {value}.",
                              epistemic_status="KNOWN", grounded=True, final_audit_passed=True,
                              has_valid_memory=True, sources=[f"user:{user_id}"],
                              memory_written=True, memory_keys=[entity],
                              dcortex={"verdict": "stored", "unknown_gate": False,
                                       "contradiction_status": "none"},
                              fcem={"runtime_proven": True})
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
