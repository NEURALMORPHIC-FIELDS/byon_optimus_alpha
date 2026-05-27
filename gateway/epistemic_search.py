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
from . import query_router as qr
from . import source_policy as sp
from . import web_search as ws

_SECRET = re.compile(
    r"(?i)\b(password|parol[ăa]|secret|secret[ăa]|private\s+key|cheie\s+(?:privat[ăa]|secret[ăa])|"
    r"api[ _-]?key|token|pin|cod\s+pin|cod\s+de\s+acces|ssn|cnp|iban|credit\s*card|"
    r"card\s+(?:bancar|de\s+credit)|cont\s+bancar)\b")
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

    # Canonical retrieval probes — English, so they reliably match the English relation/repo
    # facts regardless of the user's query language (fixes cross-lingual self-knowledge recall).
    _CANON_QUERIES = [
        "BYON architecture components D_Cortex FCE-M memory-service Claude role",
        "BYON orchestrator auditor Worker Auditor Executor epistemic contract",
        "BYON operational Level 2 FULL_LEVEL3_NOT_DECLARED; D_Cortex function; FCE-M function; Claude not authority",
    ]

    def _gather_canonical(self, mem_client, user_id: str):
        """Actively pull the committed relation/repo canonical facts so a self-architecture
        answer is complete even when the user's (e.g. Romanian) query has low cosine to the
        English facts."""
        seen, out = set(), []
        for q in self._CANON_QUERIES:
            try:
                hits = mem_client.search_facts(q, top_k=10, threshold=0.30,
                                               thread_id=user_id, scope="thread")
            except Exception:
                hits = []
            for h in hits:
                md = h.get("metadata") or {}
                src = md.get("source", "")
                if md.get("trust") in qr.COMMITTED_TIERS and (src.startswith("relation:") or src.startswith("repo:")):
                    key = h.get("content", "")
                    if key and key not in seen:
                        seen.add(key)
                        out.append(h)
        return out

    def _relation_context_hits(self, question: str, namespace_dir):
        """Cycle 12: committed relations from the relation field as memory-style context hits
        (source 'relation:...'), policy-gated. Best-effort: any failure yields no context and never
        breaks the answer path."""
        try:
            from .relation_field import lifeloop_field
            from . import relation_reports as rr
            users_root = os.path.dirname(str(namespace_dir)) if namespace_dir else "runtime/users"
            field = lifeloop_field(users_root)
            if field.is_empty():
                return []
            return rr.relation_context_hits(field, question, is_secret=False, limit=6)
        except Exception:
            return []

    def _describe_from_facts(self, question: str, committed_hits):
        """Self-knowledge synthesis: describe from the TOP canonical facts, with Claude as a
        language faculty over GROUNDED facts only (never inventing). Falls back to joining the
        facts if Claude is unavailable. Returns (answer, sources)."""
        facts, srcs = [], []
        for h in committed_hits[:8]:
            c = h.get("content") or (h.get("metadata") or {}).get("content_preview") or ""
            s = (h.get("metadata") or {}).get("source") or ""
            if c:
                facts.append(c)
            if s and s not in srcs:
                srcs.append(s)
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if key and facts:
            try:
                import httpx
                system = ("You are the language faculty of BYON. Using ONLY the grounded facts "
                          "provided, write a concise description that answers the question. Do NOT "
                          "add any information beyond the facts. If the facts are insufficient, say so.")
                content = "Question: " + question + "\nGrounded facts:\n- " + "\n- ".join(facts[:8])
                r = httpx.post("https://api.anthropic.com/v1/messages",
                               headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                        "content-type": "application/json"},
                               json={"model": os.environ.get("BYON_CLAUDE_MODEL", "claude-sonnet-4-6"),
                                     "max_tokens": 380, "temperature": 0, "system": system,
                                     "messages": [{"role": "user", "content": content}]}, timeout=30.0)
                r.raise_for_status()
                txt = "".join(b.get("text", "") for b in r.json().get("content", [])
                              if b.get("type") == "text").strip()
                if txt:
                    return txt, srcs[:6]
            except Exception:
                pass
        return ("Grounded facts: " + " | ".join(facts[:8])) if facts else "(no grounded facts)", srcs[:6]

    def run(self, *, question: str, user_id: str, session_id: str, namespace_dir,
            mem_client, learning, web_provider=None, claude_provider=None,
            allow_web: bool = False, allow_claude: bool = True, action: str = "start",
            research_trace_id: Optional[str] = None, clock: Optional[InternalResearchClock] = None,
            time_fn: Optional[Callable[[], float]] = None, recent_buffer=None) -> Dict[str, Any]:
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
                                synthesis={"epistemic_verdict": "UNKNOWN", "intent": qr.SECRET_QUERY,
                                           "query_class": sp.Q_SECRET, "source_class": sp.DISPUTED_OR_UNSAFE,
                                           "vault_primary": False,
                                           "note": "secret/credential — not searched (no Claude/web)"})

        intent = qr.classify_intent(question)
        qclass = sp.query_class(intent, question)

        # --- self-introspection: answer from RUNTIME STATE, never generic vault retrieval ----
        if intent in qr.SELF_STATE_INTENTS:
            from .self_state_provider import SelfStateProvider
            ssp = SelfStateProvider(mem_client, namespace_dir=str(namespace_dir) if namespace_dir else None)
            answer, srcs = ssp.answer_for(intent, question)
            clk.set_phase("done")
            learning.record_event("chat", question=question, status="KNOWN", grounded=True, intent=intent)
            syn = {"epistemic_verdict": "KNOWN", "memory_view": "runtime self-state",
                   "claude_view": "not used (no prior accepted)", "web_view": "not used",
                   "conflict_view": "none", "confidence": 0.9, "sources": srcs, "intent": intent,
                   "grounding": "SELF_STATE_GROUNDED", "query_class": qclass,
                   "source_class": sp.SYSTEM_CANONICAL, "vault_primary": False}
            return self._result(trace_id, clk, "KNOWN", "done", answer=answer, confidence=0.9,
                                sources_searched=["runtime:self_state", "memory-service:stats"],
                                memory_hits=[], web_results=[], claude_hypothesis=None, synthesis=syn)

        # --- operational / self-referential commands: runtime state / actions, never vault --
        if intent in qr.OPERATIONAL_INTENTS:
            from .operational_intents import OperationalIntents
            op = OperationalIntents(mem_client, str(namespace_dir) if namespace_dir else None, session_id)
            status, answer, srcs = op.handle(intent, question)
            clk.set_phase("done")
            learning.record_event("chat", question=question, status=status, intent=intent)
            syn = {"epistemic_verdict": status, "memory_view": "runtime/operational",
                   "claude_view": "not used", "web_view": "not used", "conflict_view": "none",
                   "confidence": 0.9, "sources": srcs, "intent": intent, "query_class": qclass,
                   "source_class": sp.SYSTEM_CANONICAL, "vault_primary": False}
            return self._result(trace_id, clk, status, "done", answer=answer, confidence=0.9,
                                sources_searched=srcs, memory_hits=[], web_results=[],
                                claude_hypothesis=None, synthesis=syn)

        # --- phase: internal committed + session/candidate memory ------------
        clk.set_phase("memory")
        # per-user isolation: BYON user_id maps to the memory-service thread; scope="thread"
        # also returns system-scope canonical facts (thread_id=None). Larger top_k so canonical
        # facts are in the candidate pool, then trust-tier + intent re-ranking decides priority.
        raw_hits = mem_client.search_facts(question, top_k=20, threshold=0.30,
                                           thread_id=user_id, scope="thread") if mem_client else []
        memory_hits = qr.rerank(raw_hits, intent)
        # Source-class gate on the ANSWER POOL (Cycle 3), preventing source bleed both ways:
        #  - a personal vault note (vault:* / EXTRACTED_USER_CLAIM) must NOT ground an external/
        #    objective or self/system question (it only answers "what did I write…", USER_VAULT);
        #  - a system/project fact (SYSTEM_CANONICAL / VERIFIED_PROJECT_FACT) must NOT ground a
        #    personal "my X" or objective-world question (that is the canonical→personal bleed
        #    seen when a repo chunk loosely matches "what is my …").
        def _bleeds(h) -> bool:
            src = str((h.get("metadata") or {}).get("source", ""))
            if intent != qr.USER_VAULT_QUERY and src.startswith("vault:"):
                return True
            if qclass in (sp.Q_USER_PERSONAL, sp.Q_OBJECTIVE) and \
                    sp.source_class_of(h) in (sp.SYSTEM_CANONICAL, sp.VERIFIED_PROJECT_FACT):
                return True
            return False
        memory_hits = [h for h in memory_hits if not _bleeds(h)]
        sources_searched.append(f"memory[{intent}]")
        committed = qr.committed(memory_hits)

        # SELF/architecture queries: actively gather the canonical relation/repo facts (so the
        # answer is complete cross-lingually), then synthesize a description with Claude as
        # language faculty over those GROUNDED facts.
        if intent in (qr.SELF_ARCHITECTURE_QUERY, qr.CONTRADICTION_QUERY):
            canon = self._gather_canonical(mem_client, user_id) if mem_client else []
            # Cycle 12: relation-aware normal answering — committed relations contribute CONTEXT
            # (source 'relation:...', policy-gated; vault-only objective relations excluded). They
            # rerank WITH memory facts and never outrank a real committed memory fact, and are never
            # gathered for a secret query (is_secret_query already returned above).
            rel_ctx = self._relation_context_hits(question, namespace_dir)
            pool = qr.rerank(raw_hits + canon + rel_ctx, intent)
            committed_pool = qr.committed(pool)
        else:
            committed_pool = committed
        # A personal vault note must NEVER override a fixed canonical constraint under paraphrase
        # ("BYON is Level 3", "FCE-M can approve actions", "the Auditor can be bypassed"). If such
        # a note is retrieved for a system question, surface it but mark it DISPUTED_OR_UNSAFE and
        # assert the canonical truth — never echo the note as fact.
        unsafe = []
        if intent in (qr.SELF_ARCHITECTURE_QUERY, qr.CONTRADICTION_QUERY):
            unsafe = sp.detect_unsafe_vault_claims(question, raw_hits)
            # targeted probe: a dangerous note ranked below the general top-K is still caught
            seen_txt = {t for _, t in unsafe}
            for c, t in sp.probe_unsafe_vault_claims(mem_client, user_id, question):
                if t not in seen_txt:
                    unsafe.append((c, t))
                    seen_txt.add(t)
        if unsafe:
            memory_hits = pool
            correction = sp.canonical_corrections(unsafe)
            base, srcs = self._describe_from_facts(question, committed_pool) if committed_pool else ("", [])
            answer = ("Pe scurt: " + correction + " O insemnare personala din vault sustine altceva, "
                      "dar acea afirmatie este marcata DISPUTED_OR_UNSAFE si NU reflecta starea reala "
                      "a sistemului (canonicul are prioritate fata de notele personale).")
            if base:
                answer += "\n\nContext canonic: " + base
            clk.set_phase("done")
            learning.record_event("chat", question=question, status="DISPUTED", grounded=True, intent=intent)
            syn = {"epistemic_verdict": "DISPUTED", "memory_view": "canonical vs vault claim",
                   "claude_view": "not authority", "web_view": "not needed",
                   "conflict_view": "vault note contradicts canonical constraint",
                   "confidence": 0.9, "sources": (srcs or []) + ["system:canonical"], "intent": intent,
                   "query_class": qclass, "source_class": sp.DISPUTED_OR_UNSAFE,
                   "vault_primary": False, "vault_claim_disputed": True}
            return self._result(trace_id, clk, "DISPUTED", "done", answer=answer, confidence=0.9,
                                sources_searched=sources_searched, memory_hits=memory_hits,
                                web_results=[], claude_hypothesis=None, synthesis=syn)

        if intent in (qr.SELF_ARCHITECTURE_QUERY, qr.CONTRADICTION_QUERY) and committed_pool:
            memory_hits = pool
            answer, srcs = self._describe_from_facts(question, committed_pool)
            clk.set_phase("done")
            learning.record_event("chat", question=question, status="KNOWN", grounded=True, intent=intent)
            syn = {"epistemic_verdict": "KNOWN", "memory_view": "canonical project/relation facts",
                   "claude_view": "phrased grounded facts (not authority)", "web_view": "not needed",
                   "conflict_view": "none", "confidence": 0.9, "sources": srcs, "intent": intent,
                   "query_class": qclass, "source_class": sp.SYSTEM_CANONICAL, "vault_primary": False}
            return self._result(trace_id, clk, "KNOWN", "done", answer=answer, confidence=0.9,
                                sources_searched=sources_searched, memory_hits=memory_hits,
                                web_results=[], claude_hypothesis=None, synthesis=syn)

        # recent-write buffer (Cycle 4): a fact just taught is not yet searchable in FAISS
        # (~8-11s lag). If FAISS already returned it, drop it from the buffer; otherwise, for a
        # personal recall with no committed grounding, recall it from the buffer — marked
        # honestly as RECENT_WRITE_BUFFER (pending indexing), never faked as stable FAISS.
        if recent_buffer is not None:
            for h in memory_hits:
                recent_buffer.confirm_indexed(user_id, h.get("content") or "")
            if not committed and qclass == sp.Q_USER_PERSONAL:   # only a PERSONAL recall, never
                buf = recent_buffer.recall(user_id, question)    # objective/vault/system queries
                if buf:
                    answer = buf[0]["content"]
                    clk.set_phase("done")
                    learning.record_event("chat", question=question, status="KNOWN",
                                          grounded=True, intent=intent, recent_buffer=True)
                    syn = {"epistemic_verdict": "KNOWN", "memory_view": "recent write buffer",
                           "claude_view": "not used", "web_view": "not used", "conflict_view": "none",
                           "confidence": 0.75, "sources": ["recent_write_buffer"], "intent": intent,
                           "query_class": qclass, "source_class": sp.RECENT_WRITE_BUFFER,
                           "vault_primary": False, "recent_write_buffer": True,
                           "note": "recalled from the write buffer (pending FAISS indexing)"}
                    return self._result(trace_id, clk, "KNOWN", "done", answer=answer,
                                        confidence=0.75, sources_searched=sources_searched + ["recent_write_buffer"],
                                        memory_hits=memory_hits, web_results=[], claude_hypothesis=None,
                                        synthesis=syn)

        # fast path: committed grounded answer -> KNOWN, skip Claude/web (reranked order).
        # NOT for USER_VAULT: a vault question must be answered from the user's notes and framed
        # as such, never short-circuited by a canonical/committed system fact.
        # Source-class gate (Cycle 3): the committed fact must be an ALLOWED PRIMARY source for
        # this query class — e.g. a system/project fact may not answer a personal "my X" question
        # (that would be source bleed). Otherwise fall through to honest UNKNOWN/PROVISIONAL.
        fast_ok = bool(committed) and intent != qr.USER_VAULT_QUERY
        if fast_ok:
            allowed = sp.ALLOWED_PRIMARY.get(qclass, set())
            if allowed and sp.source_class_of(committed[0]) not in allowed:
                fast_ok = False
        if fast_ok:
            syn = synthesize(question=question, memory_hits=memory_hits, candidate_hits=[],
                             claude_hypothesis=None, web_results=[], web_enabled=allow_web)
            syn["intent"] = intent
            syn["query_class"] = qclass
            syn["source_class"] = sp.source_class_of(committed[0])
            syn["vault_primary"] = sp.source_class_of(committed[0]) == sp.EXTRACTED_USER_CLAIM
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
        syn["intent"] = intent
        syn["query_class"] = qclass
        # source class of the answer: from the grounding hit (None for an empty UNKNOWN)
        grounded = memory_hits[0] if memory_hits else None
        if web_results and (syn.get("source_class") is None):
            syn["source_class"] = sp.PROVISIONAL_WEB
        elif grounded is not None and syn.get("answer"):
            syn["source_class"] = sp.source_class_of(grounded)
        else:
            syn["source_class"] = sp.UNKNOWN
        syn["vault_primary"] = (intent == qr.USER_VAULT_QUERY) or \
            (syn.get("source_class") == sp.EXTRACTED_USER_CLAIM)

        # --- vault notes are framed as the USER'S notes, not current system state -----------
        if intent == qr.USER_VAULT_QUERY and syn.get("answer"):
            note = syn["answer"]
            syn["source_class"] = sp.USER_MEMORY_GROUNDED if sp.source_class_of(grounded or {}) == \
                sp.USER_MEMORY_GROUNDED else sp.EXTRACTED_USER_CLAIM
            if qr.is_stale_limitation(note):
                syn["answer"] = ("In notele tale apare aceasta observatie ISTORICA (nu starea "
                                 "curenta a sistemului): " + note)
                syn["stale_note"] = True
            else:
                syn["answer"] = "In notele tale apare: " + note

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
        syn = synthesis or {}
        return {
            "research_trace_id": trace_id,
            "epistemic_status": status,
            "research_status": research_status,
            "answer": answer,
            "confidence": confidence,
            "grounded": status == "KNOWN",
            # source-disambiguation surface (Cycle 3) — easy to read from the API/harness
            "query_class": syn.get("query_class"),
            "source_class": syn.get("source_class"),
            "vault_primary": syn.get("vault_primary"),
            "vault_claim_disputed": syn.get("vault_claim_disputed", False),
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
