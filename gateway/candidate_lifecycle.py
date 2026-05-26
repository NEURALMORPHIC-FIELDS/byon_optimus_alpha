"""Candidate-to-commit lifecycle (Cycle 8, Track B).

Closes the learning loop: a LifeLoop task result becomes a CANDIDATE, accumulates INDEPENDENT
evidence, and only a CONSOLIDATION decision (never LifeLoop, never Claude, never FCE-M alone)
moves it to committed / disputed / archived under the existing source/trust policy.

Hard rules (enforced here):
  * candidates start provisional; commit needs evidence >= threshold AND no active contradiction;
  * a contradiction (or a conflicting canonical fact) creates a DISPUTED challenger, never an
    overwrite of a committed/canonical fact;
  * a vault/user candidate commits only as USER memory (USER_PREFERENCE), never objective truth;
  * a web-only candidate cannot commit without verification (>= MIN_WEB_SOURCES independent);
  * SYSTEM_CANONICAL is never overridden and never re-committed by a challenger;
  * secret content never becomes a candidate;
  * FCE-M state may raise priority/attention only — never flips commit/dispute by itself.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# states
CANDIDATE = "candidate"
REINFORCED = "reinforced"
COMMITTED = "committed"
DISPUTED = "disputed"
ARCHIVED = "archived"
STALE = "stale"
REJECTED = "rejected"
ACTIVE_STATES = {CANDIDATE, REINFORCED}

# decision actions
REINFORCE = "reinforce"
COMMIT = "commit"
DISPUTE = "dispute"
ARCHIVE = "archive"
KEEP = "keep_candidate"

CANONICAL_CLASSES = {"SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT"}
USER_CLASSES = {"USER_MEMORY_GROUNDED", "EXTRACTED_USER_CLAIM", "USER_PREFERENCE"}
MIN_WEB_SOURCES = 2


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _claim_key(claim: str) -> str:
    return re.sub(r"\s+", " ", (claim or "").strip().lower()).rstrip(".!? ")[:120]


def _commit_trust(source_class: Optional[str]) -> Optional[str]:
    """Trust tier a candidate would COMMIT as, per its source class (None = not committable)."""
    if source_class in USER_CLASSES:
        return "USER_PREFERENCE"          # the user's own confirmed memory — not objective truth
    if source_class == "DOMAIN_VERIFIED":
        return "DOMAIN_VERIFIED"
    if source_class == "PROVISIONAL_WEB":
        return "DOMAIN_VERIFIED"          # only after verification (checked separately)
    return None                            # canonical (already), UNKNOWN, disputed -> not committable


def evaluate_candidate(candidate: Dict[str, Any], *, fce_state: Optional[Dict[str, Any]] = None,
                       commit_evidence: int = 2, dispute_contradictions: int = 1,
                       stale_days: int = 14, now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Pure consolidation decision. FCE-M state may set priority only — never the action."""
    now_ts = now_ts if now_ts is not None else time.time()
    ev = candidate.get("evidence_count", 0)
    contra = candidate.get("contradiction_count", 0)
    sc = candidate.get("source_class")
    verified_web = (sc == "PROVISIONAL_WEB" and candidate.get("independent_web_sources", 0) >= MIN_WEB_SOURCES)
    age_days = (now_ts - float(candidate.get("created_ts", now_ts))) / 86400.0
    # FCE-M only influences attention/priority
    priority = round(ev + 2 * contra + (1.0 if (fce_state or {}).get("contested") else 0.0), 3)

    if contra >= dispute_contradictions or sc == "DISPUTED_OR_UNSAFE":
        return _d(DISPUTE, "active contradiction / unsafe", ev, contra, "needs evidence or operator", priority)
    if sc in CANONICAL_CLASSES:
        return _d(KEEP, "canonical is already authoritative; candidate not re-committed", ev, contra,
                  "no action", priority)
    committable = _commit_trust(sc) is not None and (sc != "PROVISIONAL_WEB" or verified_web)
    if ev >= commit_evidence and contra == 0 and committable:
        return _d(COMMIT, f"evidence {ev} >= {commit_evidence}, no contradiction, committable {sc}",
                  ev, contra, "store committed fact", priority)
    if sc == "PROVISIONAL_WEB" and ev >= commit_evidence and not verified_web:
        return _d(KEEP, "web evidence not verified (need independent sources)", ev, contra,
                  "verify with independent web sources or operator", priority)
    if age_days >= stale_days and ev < commit_evidence and candidate.get("confidence", 0) <= 0.5:
        return _d(ARCHIVE, f"stale ({age_days:.1f}d) and weak", ev, contra, "archive", priority)
    if ev > candidate.get("_last_eval_evidence", -1):
        return _d(REINFORCE, "new independent evidence", ev, contra, "accumulate", priority)
    return _d(KEEP, "no change", ev, contra, "wait for more evidence", priority)


def _d(action, reason, ev, contra, step, priority) -> Dict[str, Any]:
    return {"action": action, "reason": reason, "evidence_count": ev,
            "contradiction_count": contra, "required_next_step": step, "priority": priority}


class CandidateLifecycle:
    def __init__(self, namespace_dir: str | Path, mem_client: Optional[Any] = None,
                 thread_id: Optional[str] = None) -> None:
        self.dir = Path(namespace_dir)
        self.mem = mem_client
        self.thread_id = thread_id
        self.path = self.dir / "candidates_lifecycle.jsonl"
        self.audit_path = self.dir / "candidate_audit.jsonl"
        self.commit_evidence = int(os.environ.get("BYON_CANDIDATE_COMMIT_EVIDENCE", "2"))
        self.dispute_contradictions = int(os.environ.get("BYON_CANDIDATE_DISPUTE_CONTRADICTIONS", "1"))
        self.stale_days = int(os.environ.get("BYON_CANDIDATE_STALE_DAYS", "14"))
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._load()

    # -- ledger -------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    self._by_id[r["candidate_id"]] = r          # last record wins
        except (OSError, json.JSONDecodeError):
            pass

    def _save(self, rec: Dict[str, Any]) -> None:
        rec["updated_at"] = _now()
        self._by_id[rec["candidate_id"]] = rec
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _audit(self, action: str, rec: Dict[str, Any], **extra) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": _now(), "action": action,
                                    "candidate_id": rec.get("candidate_id"),
                                    "claim": rec.get("claim", "")[:120], "status": rec.get("status"),
                                    "trust_tier": rec.get("trust_tier"), **extra},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _find_topic(self, topic: str) -> List[Dict[str, Any]]:
        return [r for r in self._by_id.values()
                if r.get("topic") == topic and r.get("status") in ACTIVE_STATES]

    @staticmethod
    def _source_key(source_class, task_id, sources_used) -> str:
        srcs = "|".join(sorted(sources_used or []))
        return f"{source_class}::{task_id}::{srcs}"

    # -- ingestion / evidence merge -----------------------------------------
    def ingest_task_result(self, *, task_id: str, topic: str, claim: str,
                           sources_used: Optional[List[str]] = None, epistemic_status: str = "PROVISIONAL",
                           source_class: Optional[str] = None, source_event_ids: Optional[List[str]] = None,
                           is_secret: bool = False) -> Optional[Dict[str, Any]]:
        if is_secret or source_class == "DISPUTED_OR_UNSAFE" or not (claim or "").strip():
            return None                                         # never a candidate from secret/unsafe
        ckey = _claim_key(claim)
        skey = self._source_key(source_class, task_id, sources_used)
        same = [r for r in self._find_topic(topic) if r.get("claim_key") == ckey]
        if same:
            rec = same[0]
            if epistemic_status == "DISPUTED":
                rec["contradiction_count"] = rec.get("contradiction_count", 0) + 1
                rec["status"] = DISPUTED
            elif skey not in rec.get("source_keys", []):          # INDEPENDENT evidence only
                rec["source_keys"] = rec.get("source_keys", []) + [skey]
                rec["evidence_count"] = rec.get("evidence_count", 0) + 1
                rec["sources_used"] = sorted(set((rec.get("sources_used") or []) + (sources_used or [])))
                rec["source_event_ids"] = (rec.get("source_event_ids") or []) + (source_event_ids or [])
                rec["confidence"] = min(0.95, 0.4 + 0.2 * rec["evidence_count"])
                if source_class == "PROVISIONAL_WEB":
                    rec["independent_web_sources"] = rec.get("independent_web_sources", 0) + 1
            self._save(rec)
            self._audit("evidence_merged", rec, source_key=skey)
            return rec
        # different claim on the same topic -> a contradictory CHALLENGER
        challenger_of = None
        for r in self._find_topic(topic):
            r["contradiction_count"] = r.get("contradiction_count", 0) + 1
            self._save(r)
            challenger_of = r["candidate_id"]
        rec = {
            "candidate_id": "cand_" + uuid.uuid4().hex[:10], "topic": topic, "claim": claim[:300],
            "claim_key": ckey, "source_task_id": task_id, "source_event_ids": source_event_ids or [],
            "sources_used": sources_used or [], "source_keys": [skey],
            "evidence_count": 1, "contradiction_count": (1 if challenger_of else 0),
            "independent_web_sources": (1 if source_class == "PROVISIONAL_WEB" else 0),
            "confidence": 0.5, "trust_tier": None, "source_class": source_class,
            "status": (DISPUTED if (challenger_of or epistemic_status == "DISPUTED") else CANDIDATE),
            "challenger_of": challenger_of, "created_at": _now(), "created_ts": time.time(),
            "updated_at": _now(), "last_consolidated_at": None,
            "provenance": {"task_id": task_id, "source_class": source_class, "sources": sources_used or []}}
        self._save(rec)
        self._audit("candidate_created", rec, challenger_of=challenger_of)
        return rec

    # -- consolidation (the ONLY path that moves state) ---------------------
    def consolidate(self, *, fce_state: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        decisions = []
        for rec in list(self._by_id.values()):
            if rec.get("status") not in ACTIVE_STATES:
                continue
            decision = evaluate_candidate(rec, fce_state=fce_state, commit_evidence=self.commit_evidence,
                                          dispute_contradictions=self.dispute_contradictions,
                                          stale_days=self.stale_days)
            rec["priority"] = decision["priority"]
            rec["_last_eval_evidence"] = rec.get("evidence_count", 0)
            act = decision["action"]
            if act == COMMIT:
                self._commit(rec)
            elif act == DISPUTE:
                rec["status"] = DISPUTED
                self._save(rec)
                self._audit("disputed", rec, reason=decision["reason"])
            elif act == ARCHIVE:
                rec["status"] = ARCHIVED
                self._save(rec)
                self._audit("archived", rec, reason=decision["reason"])
            elif act == REINFORCE:
                rec["status"] = REINFORCED
                self._save(rec)
            decisions.append({"candidate_id": rec["candidate_id"], **decision})
        return decisions

    def _commit(self, rec: Dict[str, Any]) -> Optional[Any]:
        trust = _commit_trust(rec.get("source_class"))
        if trust is None:
            return None
        ctx_id = None
        if self.mem is not None:
            try:
                res = self.mem.store_fact(rec["claim"],
                                          source="lifecycle:" + (rec.get("provenance", {}).get("sources") or ["candidate"])[0],
                                          tags=["committed", "lifecycle", f"topic:{rec.get('topic','')[:40]}",
                                                f"candidate:{rec['candidate_id']}"],
                                          thread_id=self.thread_id, trust=trust)
                ctx_id = res.get("ctx_id") if isinstance(res, dict) else None
            except Exception:
                pass
        rec["status"] = COMMITTED
        rec["trust_tier"] = trust
        rec["committed_ctx_id"] = ctx_id
        rec["last_consolidated_at"] = _now()
        self._save(rec)
        self._audit("committed", rec, ctx_id=ctx_id, evidence_count=rec.get("evidence_count"))
        return ctx_id

    # -- manual operations --------------------------------------------------
    def mark_false(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        rec = self._by_id.get(candidate_id)
        if not rec:
            return None
        rec["status"] = DISPUTED
        rec["contradiction_count"] = rec.get("contradiction_count", 0) + 1
        self._save(rec)
        self._audit("manual_false", rec)
        if self.mem is not None:
            try:
                self.mem.store_fact(rec["claim"], source="user:false", tags=["disputed"],
                                    thread_id=self.thread_id, trust="DISPUTED_OR_UNSAFE",
                                    disputed=True, disputed_pattern="user marked false")
            except Exception:
                pass
        return rec

    def mark_important(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        rec = self._by_id.get(candidate_id)
        if not rec:
            return None
        rec["confidence"] = min(0.95, rec.get("confidence", 0.5) + 0.2)
        rec["important"] = True
        self._save(rec)
        self._audit("manual_important", rec)
        return rec

    def request_more_evidence(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        rec = self._by_id.get(candidate_id)
        if not rec:
            return None
        rec["required_next_step"] = "user requested more evidence"
        self._save(rec)
        self._audit("manual_request_evidence", rec)
        return rec

    def approve_commit(self, candidate_id: str, *, operator: bool = True) -> Dict[str, Any]:
        """Operator approval may LOWER the evidence threshold ONLY for the user's own memory;
        it can never override canonical, nor approve a disputed/unsafe claim as true."""
        rec = self._by_id.get(candidate_id)
        if not rec:
            return {"ok": False, "error": "not found"}
        sc = rec.get("source_class")
        if sc in CANONICAL_CLASSES:
            return {"ok": False, "refused": "cannot override SYSTEM_CANONICAL / VERIFIED_PROJECT_FACT"}
        if rec.get("status") == DISPUTED or rec.get("contradiction_count", 0) > 0:
            return {"ok": False, "refused": "cannot approve a disputed/contradicted claim as true"}
        if sc not in USER_CLASSES:
            return {"ok": False, "refused": f"manual approval only for user memory, not {sc}"}
        self._commit(rec)
        self._audit("manual_approved_commit", rec, operator=operator)
        return {"ok": True, "candidate": rec}

    def archive(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        rec = self._by_id.get(candidate_id)
        if not rec:
            return None
        rec["status"] = ARCHIVED
        self._save(rec)
        self._audit("manual_archived", rec)
        return rec

    def revive(self, topic: str, claim: str) -> Optional[Dict[str, Any]]:
        """New evidence can revive an archived candidate (same claim)."""
        ckey = _claim_key(claim)
        for r in self._by_id.values():
            if r.get("topic") == topic and r.get("claim_key") == ckey and r.get("status") == ARCHIVED:
                r["status"] = CANDIDATE
                r["evidence_count"] = r.get("evidence_count", 0) + 1
                self._save(r)
                self._audit("revived", r)
                return r
        return None

    # -- queries ------------------------------------------------------------
    def get(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(candidate_id)

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        out = [r for r in self._by_id.values() if status is None or r.get("status") == status]
        return sorted(out, key=lambda r: -r.get("priority", 0))

    def active(self) -> List[Dict[str, Any]]:
        return [r for r in self._by_id.values() if r.get("status") in ACTIVE_STATES]

    def counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {}
        for r in self._by_id.values():
            c[r.get("status", CANDIDATE)] = c.get(r.get("status", CANDIDATE), 0) + 1
        return c
