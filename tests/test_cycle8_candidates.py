"""Cycle 8 - candidate-to-commit lifecycle (decision engine, evidence merge, commit/dispute/archive)."""
from __future__ import annotations

import importlib
import time

import pytest

pytest.importorskip("httpx")

cl = importlib.import_module("gateway.candidate_lifecycle")


class FakeMem:
    def __init__(self):
        self.stored = []

    def store_fact(self, fact, *, source="", tags=None, thread_id=None, trust=None,
                   disputed=None, disputed_pattern=None):
        self.stored.append({"fact": fact, "source": source, "tags": tags or [], "trust": trust,
                            "thread_id": thread_id, "disputed": disputed})
        return {"success": True, "ctx_id": len(self.stored)}

    def search_facts(self, q, **k):
        return [{"content": s["fact"], "ctx_id": i, "metadata": {"source": s["source"], "trust": s["trust"]}}
                for i, s in enumerate(self.stored)]


def _lc(tmp_path, mem=None):
    return cl.CandidateLifecycle(tmp_path, mem_client=mem, thread_id="u")


def _ingest(lc, task_id, claim, source_class="EXTRACTED_USER_CLAIM", topic="t", status="PROVISIONAL",
            sources=None, secret=False):
    return lc.ingest_task_result(task_id=task_id, topic=topic, claim=claim,
                                 sources_used=sources or [f"src:{task_id}"], epistemic_status=status,
                                 source_class=source_class, source_event_ids=[f"ev_{task_id}"],
                                 is_secret=secret)


# ---------------- decision engine (section 1) ----------------
def _cand(**kw):
    base = {"evidence_count": 1, "contradiction_count": 0, "source_class": "EXTRACTED_USER_CLAIM",
            "created_ts": time.time(), "confidence": 0.5}
    base.update(kw)
    return base


def test_evaluate_candidate_commit():
    d = cl.evaluate_candidate(_cand(evidence_count=2), commit_evidence=2)
    assert d["action"] == cl.COMMIT


def test_evaluate_candidate_dispute():
    d = cl.evaluate_candidate(_cand(contradiction_count=1), dispute_contradictions=1)
    assert d["action"] == cl.DISPUTE


def test_evaluate_candidate_archive():
    d = cl.evaluate_candidate(_cand(evidence_count=1, created_ts=time.time() - 30 * 86400, confidence=0.3),
                              stale_days=14)
    assert d["action"] == cl.ARCHIVE


def test_evaluate_candidate_keep():
    d = cl.evaluate_candidate(_cand(evidence_count=1, _last_eval_evidence=1), commit_evidence=2)
    assert d["action"] == cl.KEEP


def test_evaluate_candidate_fce_priority_only():
    base = _cand(evidence_count=1, _last_eval_evidence=1)
    d0 = cl.evaluate_candidate(dict(base))
    d1 = cl.evaluate_candidate(dict(base), fce_state={"contested": True})
    assert d0["action"] == d1["action"] == cl.KEEP        # FCE changes nothing but priority
    assert d1["priority"] > d0["priority"]


def test_canonical_never_recommitted():
    d = cl.evaluate_candidate(_cand(evidence_count=5, source_class="SYSTEM_CANONICAL"))
    assert d["action"] == cl.KEEP                          # canonical is already authoritative


# ---------------- ingestion / evidence merge (section 2) ----------------
def test_task_result_creates_candidate(tmp_path):
    lc = _lc(tmp_path)
    rec = _ingest(lc, "t1", "the moon is made of rock")
    assert rec and rec["status"] == cl.CANDIDATE and rec["evidence_count"] == 1
    assert lc.counts()[cl.CANDIDATE] == 1


def test_same_claim_merges_independent_sources(tmp_path):
    lc = _lc(tmp_path)
    _ingest(lc, "t1", "claim X")
    rec = _ingest(lc, "t2", "claim X")                     # different task -> independent evidence
    assert rec["evidence_count"] == 2 and len(lc.active()) == 1


def test_same_source_not_counted_twice(tmp_path):
    lc = _lc(tmp_path)
    _ingest(lc, "t1", "claim Y", sources=["src:same"])
    rec = _ingest(lc, "t1", "claim Y", sources=["src:same"])   # identical source key
    assert rec["evidence_count"] == 1                      # not double-counted


def test_duplicate_task_result_not_new_candidate(tmp_path):
    lc = _lc(tmp_path)
    _ingest(lc, "t1", "claim Z")
    _ingest(lc, "t1", "claim Z")
    assert len(lc.list()) == 1


def test_contradictory_claim_creates_challenger(tmp_path):
    lc = _lc(tmp_path)
    a = _ingest(lc, "t1", "the deadline is Monday", topic="deadline")
    b = _ingest(lc, "t2", "the deadline is Friday", topic="deadline")   # different claim, same topic
    assert b["candidate_id"] != a["candidate_id"]
    assert b.get("challenger_of") == a["candidate_id"]
    assert lc.get(a["candidate_id"])["contradiction_count"] >= 1


def test_secret_never_creates_candidate(tmp_path):
    lc = _lc(tmp_path)
    assert _ingest(lc, "t1", "my password is hunter2", secret=True) is None
    assert lc.list() == []


# ---------------- commit (section 3) ----------------
def test_candidate_commits_after_threshold_to_memory_service(tmp_path):
    mem = FakeMem()
    lc = _lc(tmp_path, mem)
    _ingest(lc, "t1", "alpha fact")
    _ingest(lc, "t2", "alpha fact")                        # evidence_count -> 2
    lc.consolidate()
    rec = lc.list(cl.COMMITTED)[0]
    assert rec["status"] == cl.COMMITTED
    assert any(s["fact"] == "alpha fact" and "committed" in s["tags"] for s in mem.stored)


def test_commit_includes_provenance_and_respects_source_class(tmp_path):
    mem = FakeMem()
    lc = _lc(tmp_path, mem)
    _ingest(lc, "t1", "beta fact", source_class="EXTRACTED_USER_CLAIM")
    _ingest(lc, "t2", "beta fact", source_class="EXTRACTED_USER_CLAIM")
    lc.consolidate()
    stored = [s for s in mem.stored if s["fact"] == "beta fact"][0]
    assert stored["trust"] == "USER_PREFERENCE"            # user memory, NOT objective truth
    assert any(t.startswith("candidate:") for t in stored["tags"])


def test_vault_candidate_not_objective_truth(tmp_path):
    mem = FakeMem()
    lc = _lc(tmp_path, mem)
    _ingest(lc, "t1", "vault claim", source_class="EXTRACTED_USER_CLAIM")
    _ingest(lc, "t2", "vault claim", source_class="EXTRACTED_USER_CLAIM")
    lc.consolidate()
    stored = [s for s in mem.stored if s["fact"] == "vault claim"][0]
    assert stored["trust"] not in ("DOMAIN_VERIFIED", "VERIFIED_PROJECT_FACT", "SYSTEM_CANONICAL")


def test_web_candidate_requires_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("BYON_CANDIDATE_COMMIT_EVIDENCE", "1")
    mem = FakeMem()
    lc = _lc(tmp_path, mem)
    _ingest(lc, "t1", "web claim", source_class="PROVISIONAL_WEB")   # 1 web source < MIN_WEB_SOURCES
    lc.consolidate()
    assert lc.list(cl.COMMITTED) == []                     # not committed without verification
    _ingest(lc, "t2", "web claim", source_class="PROVISIONAL_WEB")   # now 2 independent web sources
    lc.consolidate()
    assert lc.list(cl.COMMITTED) and lc.list(cl.COMMITTED)[0]["trust_tier"] == "DOMAIN_VERIFIED"


def test_committed_fact_not_from_secret(tmp_path):
    mem = FakeMem()
    lc = _lc(tmp_path, mem)
    _ingest(lc, "t1", "secret stuff", secret=True)
    _ingest(lc, "t2", "secret stuff", secret=True)
    lc.consolidate()
    assert mem.stored == []                                # nothing committed from secret content


# ---------------- dispute / challenger (section 4) ----------------
def test_contradiction_marks_disputed(tmp_path):
    lc = _lc(tmp_path)
    _ingest(lc, "t1", "x is up", topic="x")
    _ingest(lc, "t2", "x is down", topic="x")              # contradiction
    lc.consolidate()
    assert lc.counts().get(cl.DISPUTED, 0) >= 1


def test_disputed_status_status_from_disputed_result(tmp_path):
    lc = _lc(tmp_path)
    rec = _ingest(lc, "t1", "shaky claim", status="DISPUTED")
    assert rec["status"] == cl.DISPUTED


def test_user_claim_challenger_does_not_override_system(tmp_path):
    mem = FakeMem()
    lc = _lc(tmp_path, mem)
    # a user-claim candidate that conflicts with a canonical fact must not commit/override
    rec = _ingest(lc, "t1", "BYON is Level 3", source_class="EXTRACTED_USER_CLAIM", topic="level")
    _ingest(lc, "t2", "BYON is Level 2 (FULL_LEVEL3_NOT_DECLARED)", source_class="SYSTEM_CANONICAL",
            topic="level")                                  # canonical challenger -> contradiction
    lc.consolidate()
    # the user claim is disputed, never committed as truth
    assert lc.get(rec["candidate_id"])["status"] in (cl.DISPUTED,)
    assert not any(s["fact"] == "BYON is Level 3" and s["trust"] in ("VERIFIED_PROJECT_FACT", "DOMAIN_VERIFIED")
                   for s in mem.stored)


# ---------------- archive / stale (section 5) ----------------
def test_stale_candidate_archived_and_not_active(tmp_path):
    lc = _lc(tmp_path)
    rec = _ingest(lc, "t1", "weak old claim")
    lc._by_id[rec["candidate_id"]]["created_ts"] = time.time() - 40 * 86400   # very old, weak
    lc.consolidate()
    assert lc.get(rec["candidate_id"])["status"] == cl.ARCHIVED
    assert all(r["status"] != cl.ARCHIVED for r in lc.active())   # not in active pool


def test_archived_candidate_revived_by_new_evidence(tmp_path):
    lc = _lc(tmp_path)
    rec = _ingest(lc, "t1", "revivable claim")
    lc._by_id[rec["candidate_id"]]["created_ts"] = time.time() - 40 * 86400
    lc.consolidate()
    assert lc.get(rec["candidate_id"])["status"] == cl.ARCHIVED
    revived = lc.revive("t", "revivable claim")
    assert revived and revived["status"] == cl.CANDIDATE


# ---------------- manual operations (section 6) ----------------
def test_manual_false_marks_disputed(tmp_path):
    mem = FakeMem()
    lc = _lc(tmp_path, mem)
    rec = _ingest(lc, "t1", "claim to reject")
    lc.mark_false(rec["candidate_id"])
    assert lc.get(rec["candidate_id"])["status"] == cl.DISPUTED


def test_manual_archive(tmp_path):
    lc = _lc(tmp_path)
    rec = _ingest(lc, "t1", "archive me")
    lc.archive(rec["candidate_id"])
    assert lc.get(rec["candidate_id"])["status"] == cl.ARCHIVED


def test_manual_approval_cannot_override_canonical(tmp_path):
    mem = FakeMem()
    lc = _lc(tmp_path, mem)
    rec = _ingest(lc, "t1", "canonical-ish claim", source_class="SYSTEM_CANONICAL")
    r = lc.approve_commit(rec["candidate_id"])
    assert r["ok"] is False and "canonical" in r["refused"].lower()


def test_manual_approval_user_memory_below_threshold(tmp_path):
    mem = FakeMem()
    lc = _lc(tmp_path, mem)
    rec = _ingest(lc, "t1", "my note", source_class="EXTRACTED_USER_CLAIM")   # only 1 evidence
    r = lc.approve_commit(rec["candidate_id"])
    assert r["ok"] is True and lc.get(rec["candidate_id"])["status"] == cl.COMMITTED


def test_manual_approval_cannot_approve_disputed(tmp_path):
    lc = _lc(tmp_path, FakeMem())
    rec = _ingest(lc, "t1", "contested", status="DISPUTED")
    r = lc.approve_commit(rec["candidate_id"])
    assert r["ok"] is False


def test_counts_and_audit_written(tmp_path):
    lc = _lc(tmp_path, FakeMem())
    _ingest(lc, "t1", "c1")
    _ingest(lc, "t2", "c1")
    lc.consolidate()
    assert (tmp_path / "candidate_audit.jsonl").exists()
    assert lc.counts().get(cl.COMMITTED, 0) == 1
