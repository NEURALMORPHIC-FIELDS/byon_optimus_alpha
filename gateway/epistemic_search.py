"""Epistemic Search Loop — BYON's honest exhaustion of available sources before UNKNOWN.

Composes the CANONICAL pieces (it does not reimplement them):
  internal/committed memory + session/candidates  ← memory-service (FAISS + trust tiers)
  Claude hypothesis/strategy                       ← ClaudeHypothesisProvider (not authority)
  web evidence                                     ← web_search provider (candidates, not truth)
  multi-perspective synthesis + verdict            ← perspective_synthesis
  research budget + stress + 5-min permission      ← InternalResearchClock
  learning side-effect (candidate→commit)          ← continuous_learning over memory-service

UNKNOWN is allowed only after the honest available sources are exhausted. Claude prior alone
is never KNOWN (PROVISIONAL_UNVERIFIED). Web alone is PROVISIONAL (candidate), DISPUTED if
sources conflict. Secrets/credentials are never sent to Claude or the web.
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Any, Callable, Dict, List, Optional

from .internal_clock import (InternalResearchClock, PRESSURE_HIGH_CERTAINTY,
                             PRESSURE_SOURCES_CONFLICT, PRESSURE_UNSAFE_TOPIC, PRESSURE_WEB_FAIL)
from .perspective_synthesis import synthesize
from . import web_search as ws

_SECRET = re.compile(r"(?i)\b(password|secret|private key|api[ _-]?key|token|pin|ssn|credit\s*card)\b")
_HIGH_CERTAINTY = re.compile(r"(?i)\b(exactly|precisely|definitely|certain|guarantee|for sure)\b")

# Active research turns: research_trace_id -> InternalResearchClock (for continue/conclude).
_REGISTRY: Dict[str, InternalResearchClock] = {}


def is_secret_query(message: str) -> bool:
    return bool(_SECRET.search(message or ""))


class ClaudeHypothesisProvider:
    """Asks Claude for a hypothesis + search strategy. Claude is NOT the authority and may
    not, alone, produce KNOWN. Never called for secrets/credentials."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-6") -> None:
        self.api_key = (api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        self.model = model
        self.available = bool(self.api_key)

    def propose(self, question: str, memory_hits: List[Dict[str, Any]],
                uncertainty: str = "") -> Optional[Dict[str, Any]]:
        if not self.available:
            return None
        try:
            import httpx
            system = ("You are the reasoning faculty of BYON. Propose a HYPOTHESIS and a search "
                      "strategy for the question. You are NOT the final authority and your answer "
                      "is NOT truth until verified. Reply ONLY with compact JSON: "
                      '{"hypothesis": str, "suggested_search_queries": [str], '
                      '"possible_entities": [str], "confidence": 0..1, "requires_verification": true}')
            content = f"Question: {question}\nKnown memory: {[h.get('content','') for h in memory_hits][:3]}"
            r = httpx.post("https://api.anthropic.com/v1/messages",
                           headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                                    "content-type": "application/json"},
                           json={"model": self.model, "max_tokens": 400, "system": system,
                                 "messages": [{"role": "user", "content": content}]}, timeout=30.0)
            r.raise_for_status()
            txt = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
            import json as _json
            m = re.search(r"\{.*\}", txt, re.S)
            data = _json.loads(m.group(0)) if m else {}
            data["requires_verification"] = True
            return data
        except Exception:
            return None


class EpistemicSearch:
    def __init__(self) -> None:
        self.budget = float(os.environ.get("BYON_RESEARCH_BUDGET_SECONDS", "300"))
        self.extension = float(os.environ.get("BYON_RESEARCH_EXTENSION_SECONDS", "300"))
        self.max_ext = int(os.environ.get("BYON_RESEARCH_MAX_EXTENSIONS", "1"))
        self.auto_commit_web = os.environ.get("BYON_AUTO_COMMIT_VERIFIED_WEB", "false").strip().lower() in (
            "1", "true", "yes", "on")
        self.min_web_sources = int(os.environ.get("BYON_WEB_MIN_SOURCES", "2"))

    def _clock(self, action: str, trace_id: str, time_fn: Optional[Callable[[], float]]) -> InternalResearchClock:
        if action == "start" or trace_id not in _REGISTRY:
            clk = InternalResearchClock(deadline_seconds=self.budget, extension_seconds=self.extension,
                                        max_extensions=self.max_ext,
                                        time_fn=time_fn or __import__("time").time)
            _REGISTRY[trace_id] = clk
            return clk
        return _REGISTRY[trace_id]

    def run(self, *, question: str, user_id: str, session_id: str, namespace_dir,
            mem_client, learning, web_provider=None, claude_provider=None,
            allow_web: bool = False, allow_claude: bool = True, action: str = "start",
            research_trace_id: Optional[str] = None, clock: Optional[InternalResearchClock] = None,
            time_fn: Optional[Callable[[], float]] = None) -> Dict[str, Any]:
        trace_id = research_trace_id or ("research_" + uuid.uuid4().hex)
        clk = clock or self._clock(action, trace_id, time_fn)
        if action == "continue":  # a continuation extends the budget by one window
            clk.extend()
        sources_searched: List[str] = []
        web_results: List[Any] = []
        claude_hypothesis: Optional[Dict[str, Any]] = None

        if _HIGH_CERTAINTY.search(question):
            clk.add_pressure("high_certainty_demand", PRESSURE_HIGH_CERTAINTY)

        # --- secret/credential guard: never search Claude or web -------------
        if is_secret_query(question):
            clk.add_pressure("unsafe_topic", PRESSURE_UNSAFE_TOPIC)
            clk.set_phase("done")
            learning.record_event("chat", question=question, status="UNKNOWN", secret=True)
            return self._result(trace_id, clk, "UNKNOWN", "done",
                                answer="", confidence=0.0, sources_searched=["memory"],
                                memory_hits=[], web_results=[], claude_hypothesis=None,
                                synthesis={"epistemic_verdict": "UNKNOWN",
                                           "note": "secret/credential — not searched (no Claude/web)"})

        # --- phase: internal committed + session/candidate memory ------------
        clk.set_phase("memory")
        # per-user isolation: BYON user_id maps to the memory-service thread; scope="thread"
        # also returns system-scope canonical facts (thread_id=None).
        memory_hits = mem_client.search_facts(question, top_k=5, threshold=0.35,
                                              thread_id=user_id, scope="thread") if mem_client else []
        sources_searched.append("memory")
        committed = [h for h in memory_hits if ((h.get("metadata") or {}).get("trust") or h.get("trust"))
                     in ("VERIFIED_PROJECT_FACT", "DOMAIN_VERIFIED", "USER_PREFERENCE")]
        # fast path: committed grounded answer -> KNOWN, skip Claude/web
        if committed:
            syn = synthesize(question=question, memory_hits=memory_hits, candidate_hits=[],
                             claude_hypothesis=None, web_results=[], web_enabled=allow_web)
            clk.set_phase("done")
            learning.record_event("chat", question=question, status=syn["epistemic_verdict"], grounded=True)
            return self._result(trace_id, clk, syn["epistemic_verdict"], "done",
                                answer=syn["answer"], confidence=syn["confidence"],
                                sources_searched=sources_searched, memory_hits=memory_hits,
                                web_results=[], claude_hypothesis=None, synthesis=syn)

        # --- budget gate: ask permission instead of silently continuing ------
        if clk.deadline_reached() and action != "conclude":
            clk.set_phase("permission")
            return self._result(trace_id, clk, "NEEDS_MORE_TIME", "needs_more_time",
                                answer=("I searched the available sources and do not yet have a "
                                        "conclusive answer. Continue for another "
                                        f"{int(self.extension)//60} minutes?"),
                                confidence=0.0, sources_searched=sources_searched,
                                memory_hits=memory_hits, web_results=[], claude_hypothesis=None,
                                synthesis={"epistemic_verdict": "NEEDS_MORE_TIME"},
                                can_extend=clk.can_extend())

        # --- phase: Claude hypothesis (not authority) ------------------------
        if allow_claude and claude_provider is not None and getattr(claude_provider, "available", True):
            clk.set_phase("claude")
            claude_hypothesis = claude_provider.propose(question, memory_hits)
            if claude_hypothesis:
                sources_searched.append("claude")

        # --- phase: web evidence (candidates, not truth) ---------------------
        if allow_web and web_provider is not None and getattr(web_provider, "available", False):
            clk.set_phase("web")
            queries = [question]
            for q in (claude_hypothesis or {}).get("suggested_search_queries", []) or []:
                if q and q not in queries:
                    queries.append(q)
            queries = queries[:5]
            seen_domains = set()
            for q in queries:
                try:
                    for r in web_provider.search(q, max_results=5):
                        if r.source_domain and r.source_domain in seen_domains:
                            continue
                        seen_domains.add(r.source_domain)
                        web_results.append(r)
                except Exception:
                    clk.add_pressure("web_failed", PRESSURE_WEB_FAIL)
            sources_searched.append(f"web:{getattr(web_provider, 'name', 'web')}")
            if not web_results:
                clk.add_pressure("web_failed", PRESSURE_WEB_FAIL)

        # --- phase: synthesis + verdict --------------------------------------
        clk.set_phase("synthesis")
        syn = synthesize(question=question, memory_hits=memory_hits, candidate_hits=[],
                         claude_hypothesis=claude_hypothesis, web_results=web_results,
                         web_enabled=allow_web, auto_commit_web=self.auto_commit_web,
                         min_web_sources=self.min_web_sources)
        if len(syn.get("distinct_claims", [])) >= 2:
            clk.add_pressure("sources_conflict", PRESSURE_SOURCES_CONFLICT)

        # --- learning side-effect -------------------------------------------
        if syn.get("candidate"):
            cand = syn["candidate"]
            learning.store_web_candidate(cand["value"], cand.get("sources", []), question=question)
        learning.record_event("chat", question=question, status=syn["epistemic_verdict"],
                              grounded=(syn["epistemic_verdict"] == "KNOWN"))
        learning.record_research_trace({"research_trace_id": trace_id, "question": question,
                                        "status": syn["epistemic_verdict"],
                                        "sources_searched": sources_searched,
                                        "stress_percent": clk.stress_percent(),
                                        "extension_count": clk.extension_count})
        clk.set_phase("done")
        return self._result(trace_id, clk, syn["epistemic_verdict"], "done",
                            answer=syn["answer"], confidence=syn["confidence"],
                            sources_searched=sources_searched, memory_hits=memory_hits,
                            web_results=[r.to_dict() for r in web_results],
                            claude_hypothesis=claude_hypothesis, synthesis=syn)

    @staticmethod
    def _result(trace_id, clk, status, research_status, *, answer, confidence, sources_searched,
                memory_hits, web_results, claude_hypothesis, synthesis, can_extend=None) -> Dict[str, Any]:
        snap = clk.snapshot()
        return {
            "research_trace_id": trace_id,
            "epistemic_status": status,
            "research_status": research_status,
            "answer": answer,
            "confidence": confidence,
            "grounded": status == "KNOWN",
            "clock": snap,
            "stress_percent": snap["stress_percent"],
            "phase": snap["phase"],
            "sources_searched": sources_searched,
            "memory_hits": [{"content": h.get("content", ""), "score": h.get("score"),
                             "trust": (h.get("metadata") or {}).get("trust")} for h in (memory_hits or [])],
            "web_results": web_results or [],
            "claude_hypothesis": claude_hypothesis,
            "synthesis": synthesis,
            "can_extend": can_extend if can_extend is not None else clk.can_extend(),
        }
