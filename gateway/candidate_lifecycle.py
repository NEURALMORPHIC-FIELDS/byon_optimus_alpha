# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
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
  * FCE-M state may raise priority/attention only - never flips commit/dispute by itself.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import evidence_semantics as es

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
VERIFIED_CLASSES = {"DOMAIN_VERIFIED", "VERIFIED_PROJECT_FACT"}
MIN_WEB_SOURCES = 2


def evidence_quality_score(candidate: Dict[str, Any], *, stale_days: int = 14,
                           now_ts: Optional[float] = None) -> float:
    """A 0..1 quality score (Cycle 9): evidence COUNT alone is too weak. Rewards independent
    sources / class diversity / verified sources / user confirmation; penalises same-source
    repetition, unverified web, contradiction, staleness and low semantic confidence."""
    now_ts = now_ts if now_ts is not None else time.time()
    ev = candidate.get("evidence_count", 0)
    classes = {str(k).split("::", 1)[0] for k in candidate.get("source_keys", [])}
    sc = candidate.get("source_class")
    has_verified = bool(classes & VERIFIED_CLASSES) or sc in VERIFIED_CLASSES
    unverified_web = (sc == "PROVISIONAL_WEB" and candidate.get("independent_web_sources", 0) < MIN_WEB_SOURCES)
    age_days = (now_ts - float(candidate.get("created_ts", now_ts))) / 86400.0
    stale = age_days >= stale_days
    low_sem = candidate.get("semantic_confidence", 1.0) < 0.5
    q = 0.5 + 0.15 * min(ev, 3) + 0.1 * (1 if len(classes) >= 2 else 0)
    q += 0.2 * (1 if has_verified else 0) + 0.1 * (1 if candidate.get("important") else 0)
    q -= 0.3 * (1 if candidate.get("contradiction_count", 0) > 0 else 0)
    q -= 0.2 * (1 if unverified_web else 0) + 0.1 * (1 if stale else 0) + 0.1 * (1 if low_sem else 0)
    return round(max(0.0, min(1.0, q)), 3)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _claim_key(claim: str) -> str:
    return re.sub(r"\s+", " ", (claim or "").strip().lower()).rstrip(".!? ")[:120]


def _commit_trust(source_class: Optional[str]) -> Optional[str]:
    """Trust tier a candidate would COMMIT as, per its source class (None = not committable)."""
    if source_class in USER_CLASSES:
        return "USER_PREFERENCE"          # the user's own confirmed memory - not objective truth
    if source_class == "DOMAIN_VERIFIED":
        return "DOMAIN_VERIFIED"
    if source_class == "PROVISIONAL_WEB":
        return "DOMAIN_VERIFIED"          # only after verification (checked separately)
    return None                            # canonical (already), UNKNOWN, disputed -> not committable


def evaluate_candidate(candidate: Dict[str, Any], *, fce_state: Optional[Dict[str, Any]] = None,
                       commit_evidence: int = 2, dispute_contradictions: int = 1,
                       stale_days: int = 14, commit_quality: float = 0.70,
                       now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Pure consolidation decision. FCE-M state may set priority only - never the action.
    Commit requires evidence_count AND evidence_quality AND no contradiction AND committable."""
    now_ts = now_ts if now_ts is not None else time.time()
    ev = candidate.get("evidence_count", 0)
    contra = candidate.get("contradiction_count", 0)
    sc = candidate.get("source_class")
    quality = evidence_quality_score(candidate, stale_days=stale_days, now_ts=now_ts)
    verified_web = (sc == "PROVISIONAL_WEB" and candidate.get("independent_web_sources", 0) >= MIN_WEB_SOURCES)
    age_days = (now_ts - float(candidate.get("created_ts", now_ts))) / 86400.0
    priority = round(ev + 2 * contra + (1.0 if (fce_state or {}).get("contested") else 0.0), 3)

    if contra >= dispute_contradictions or sc == "DISPUTED_OR_UNSAFE":
        return _d(DISPUTE, "active contradiction / unsafe", ev, contra, "needs evidence or operator",
                  priority, quality)
    if sc in CANONICAL_CLASSES:
        return _d(KEEP, "canonical is already authoritative; candidate not re-committed", ev, contra,
                  "no action", priority, quality)
    committable = _commit_trust(sc) is not None and (sc != "PROVISIONAL_WEB" or verified_web)
    if ev >= commit_evidence and contra == 0 and committable and quality >= commit_quality:
        return _d(COMMIT, f"evidence {ev}>= {commit_evidence}, quality {quality}>= {commit_quality}, "
                  f"no contradiction, committable {sc}", ev, contra, "store committed fact", priority, quality)
    if ev >= commit_evidence and contra == 0 and committable and quality < commit_quality:
        return _d(KEEP, f"evidence ok but quality {quality} < {commit_quality}", ev, contra,
                  "need higher-quality / more independent evidence", priority, quality)
    if sc == "PROVISIONAL_WEB" and ev >= commit_evidence and not verified_web:
        return _d(KEEP, "web evidence not verified (need independent sources)", ev, contra,
                  "verify with independent web sources or operator", priority, quality)
    if age_days >= stale_days and ev < commit_evidence and candidate.get("confidence", 0) <= 0.5:
        return _d(ARCHIVE, f"stale ({age_days:.1f}d) and weak", ev, contra, "archive", priority, quality)
    if ev > candidate.get("_last_eval_evidence", -1):
        return _d(REINFORCE, "new independent evidence", ev, contra, "accumulate", priority, quality)
    return _d(KEEP, "no change", ev, contra, "wait for more evidence", priority, quality)


def _d(action, reason, ev, contra, step, priority, quality=None) -> Dict[str, Any]:
    return {"action": action, "reason": reason, "evidence_count": ev,
            "contradiction_count": contra, "required_next_step": step, "priority": priority,
            "evidence_quality_score": quality}


class CandidateLifecycle:
    def __init__(self, namespace_dir: str | Path, mem_client: Optional[Any] = None,
                 thread_id: Optional[str] = None) -> None:
        self.dir = Path(namespace_dir)
        self.mem = mem_client
        self.thread_id = thread_id
        self.path = self.dir / "candidates_lifecycle.jsonl"
        self.audit_path = self.dir / "candidate_audit.jsonl"
        self.disputes_path = self.dir / "candidate_disputes.jsonl"
        self.commit_evidence = int(os.environ.get("BYON_CANDIDATE_COMMIT_EVIDENCE", "2"))
        self.dispute_contradictions = int(os.environ.get("BYON_CANDIDATE_DISPUTE_CONTRADICTIONS", "1"))
        self.stale_days = int(os.environ.get("BYON_CANDIDATE_STALE_DAYS", "14"))
        self.commit_quality = float(os.environ.get("BYON_CANDIDATE_COMMIT_QUALITY", "0.70"))
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
    def _merge_evidence(self, rec: Dict[str, Any], *, skey: str, sources_used, source_event_ids,
                        source_class, relation, rel_conf, method) -> Dict[str, Any]:
        if skey not in rec.get("source_keys", []):                # INDEPENDENT evidence only
            rec["source_keys"] = rec.get("source_keys", []) + [skey]
            rec["evidence_count"] = rec.get("evidence_count", 0) + 1
            rec["sources_used"] = sorted(set((rec.get("sources_used") or []) + (sources_used or [])))
            rec["source_event_ids"] = (rec.get("source_event_ids") or []) + (source_event_ids or [])
            rec["confidence"] = min(0.95, 0.4 + 0.2 * rec["evidence_count"])
            if source_class == "PROVISIONAL_WEB":
                rec["independent_web_sources"] = rec.get("independent_web_sources", 0) + 1
        rec["semantic_relation"] = relation
        rec["semantic_confidence"] = rel_conf
        rec["relation_method"] = method
        self._save(rec)
        self._audit("evidence_merged", rec, source_key=skey, relation=relation, method=method)
        return rec

    def ingest_task_result(self, *, task_id: str, topic: str, claim: str,
                           sources_used: Optional[List[str]] = None, epistemic_status: str = "PROVISIONAL",
                           source_class: Optional[str] = None, source_event_ids: Optional[List[str]] = None,
                           is_secret: bool = False) -> Optional[Dict[str, Any]]:
        if is_secret or source_class == "DISPUTED_OR_UNSAFE" or not (claim or "").strip():
            return None                                         # never a candidate from secret/unsafe
        ckey = _claim_key(claim)
        skey = self._source_key(source_class, task_id, sources_used)
        existing = self._find_topic(topic)
        # Cycle 9: classify the SEMANTIC relation to each active candidate on the topic, then act on
        # the strongest (canonical_conflict/contradicts > same/supports > narrows/broadens).
        rels = []
        for r in existing:
            rel = es.classify_evidence_relation(
                claim, r.get("claim", ""),
                context={"source_class_a": source_class, "source_class_b": r.get("source_class"),
                         "is_secret": is_secret}, sources=sources_used)
            rels.append((r, rel))

        conflict = next(((r, rel) for r, rel in rels
                         if rel["relation"] in (es.CONTRADICTS, es.CANONICAL_CONFLICT)), None)
        if conflict or epistemic_status == "DISPUTED":
            incumbent, rel = (conflict if conflict else (existing[0] if existing else None,
                              {"relation": es.CONTRADICTS, "confidence": 0.5, "reason": "task returned DISPUTED",
                               "method": "task_status"}))
            challenger = self._new_candidate(task_id, topic, claim, ckey, skey, sources_used,
                                             source_event_ids, source_class, status=DISPUTED,
                                             challenger_of=(incumbent or {}).get("candidate_id"),
                                             relation=rel["relation"], rel_conf=rel["confidence"],
                                             method=rel["method"], contradiction=1)
            if incumbent:
                incumbent["contradiction_count"] = incumbent.get("contradiction_count", 0) + 1
                incumbent.setdefault("related_candidate_ids", [])
                if challenger["candidate_id"] not in incumbent["related_candidate_ids"]:
                    incumbent["related_candidate_ids"].append(challenger["candidate_id"])
                self._save(incumbent)
                self._write_dispute(incumbent, challenger, rel, source_class)
            return challenger

        merge = next(((r, rel) for r, rel in rels if rel["relation"] in (es.SAME, es.SUPPORTS)), None)
        if merge:
            r, rel = merge
            return self._merge_evidence(r, skey=skey, sources_used=sources_used,
                                        source_event_ids=source_event_ids, source_class=source_class,
                                        relation=rel["relation"], rel_conf=rel["confidence"],
                                        method=rel["method"])

        related = [(r, rel) for r, rel in rels if rel["relation"] in (es.NARROWS, es.BROADENS)]
        rec = self._new_candidate(task_id, topic, claim, ckey, skey, sources_used, source_event_ids,
                                  source_class, status=CANDIDATE, challenger_of=None,
                                  relation=(related[0][1]["relation"] if related else None),
                                  rel_conf=(related[0][1]["confidence"] if related else 1.0),
                                  method=(related[0][1]["method"] if related else "new"),
                                  related_ids=[r["candidate_id"] for r, _ in related])
        for r, _ in related:                                    # link both directions, do NOT merge
            r.setdefault("related_candidate_ids", [])
            if rec["candidate_id"] not in r["related_candidate_ids"]:
                r["related_candidate_ids"].append(rec["candidate_id"])
                self._save(r)
        return rec

    def _new_candidate(self, task_id, topic, claim, ckey, skey, sources_used, source_event_ids,
                       source_class, *, status, challenger_of, relation, rel_conf, method,
                       contradiction=0, related_ids=None) -> Dict[str, Any]:
        rec = {
            "candidate_id": "cand_" + uuid.uuid4().hex[:10], "topic": topic, "claim": claim[:300],
            "claim_key": ckey, "source_task_id": task_id, "source_event_ids": source_event_ids or [],
            "sources_used": sources_used or [], "source_keys": [skey],
            "evidence_count": 1, "contradiction_count": contradiction,
            "independent_web_sources": (1 if source_class == "PROVISIONAL_WEB" else 0),
            "confidence": 0.5, "trust_tier": None, "source_class": source_class,
            "semantic_relation": relation, "semantic_confidence": rel_conf, "relation_method": method,
            "related_candidate_ids": related_ids or [],
            "status": status, "challenger_of": challenger_of,
            "created_at": _now(), "created_ts": time.time(), "updated_at": _now(),
            "last_consolidated_at": None,
            "provenance": {"task_id": task_id, "source_class": source_class, "sources": sources_used or []}}
        self._save(rec)
        self._audit("candidate_created", rec, challenger_of=challenger_of, relation=relation)
        return rec

    def _write_dispute(self, incumbent: Dict[str, Any], challenger: Dict[str, Any],
                       rel: Dict[str, Any], source_class_a) -> None:
        sca, scb = source_class_a, incumbent.get("source_class")
        relation = rel["relation"]
        if relation == es.CANONICAL_CONFLICT or scb in CANONICAL_CLASSES:
            step = "canonical_overrides"
        elif sca in USER_CLASSES or scb in USER_CLASSES:
            step = "ask_user_for_source"
        elif "PROVISIONAL_WEB" in (sca, scb):
            step = "search_verified_source"
        else:
            step = "request_operator_resolution"
        rec = {"ts": _now(), "candidate_id": incumbent["candidate_id"],
               "challenger_id": challenger["candidate_id"], "relation": relation,
               "evidence_a": incumbent.get("claim", "")[:200], "evidence_b": challenger.get("claim", "")[:200],
               "source_class_a": scb, "source_class_b": sca,
               "reason": rel.get("reason"), "required_next_step": step}
        try:
            with self.disputes_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self._audit("dispute_recorded", challenger, **{"relation": relation, "required_next_step": step})

    def list_disputes(self) -> List[Dict[str, Any]]:
        if not self.disputes_path.exists():
            return []
        try:
            return [json.loads(x) for x in self.disputes_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        except (OSError, json.JSONDecodeError):
            return []

    # -- consolidation (the ONLY path that moves state) ---------------------
    def consolidate(self, *, fce_state: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        decisions = []
        for rec in list(self._by_id.values()):
            if rec.get("status") not in ACTIVE_STATES:
                continue
            decision = evaluate_candidate(rec, fce_state=fce_state, commit_evidence=self.commit_evidence,
                                          dispute_contradictions=self.dispute_contradictions,
                                          stale_days=self.stale_days, commit_quality=self.commit_quality)
            rec["priority"] = decision["priority"]
            rec["evidence_quality_score"] = decision["evidence_quality_score"]
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
