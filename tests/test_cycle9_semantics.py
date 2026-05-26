"""Cycle 9 — semantic contradiction & evidence quality.

T1 classifier relations, T2 semantic merge/dispute in the lifecycle, T3 evidence-quality commit
gate, T4 dispute explanation records. The classifier is deterministic-first (lexical + canonical +
polarity); any Claude/NLI pass is advisory only and never overrides source policy or decides truth.
"""
from __future__ import annotations

import importlib
import time

import pytest

pytest.importorskip("httpx")

es = importlib.import_module("gateway.evidence_semantics")
cl = importlib.import_module("gateway.candidate_lifecycle")


# ----------------------------------------------------------------------------
# T1 — classifier
# ----------------------------------------------------------------------------
def test_same_claim_paraphrase_detected():
    r = es.classify_evidence_relation("The capital of France is Paris",
                                      "Paris is the capital of France")
    assert r["relation"] == es.SAME


def test_support_relation_detected():
    r = es.classify_evidence_relation("The team won the championship in 2020",
                                      "The team won the championship final")
    assert r["relation"] == es.SUPPORTS


def test_contradiction_relation_detected():
    r = es.classify_evidence_relation("The server is up", "The server is down")
    assert r["relation"] == es.CONTRADICTS


def test_unrelated_claim_not_merged():
    r = es.classify_evidence_relation("I like coffee in the morning",
                                      "The Eiffel Tower is in Paris")
    assert r["relation"] == es.UNRELATED


def test_canonical_conflict_overrides_semantic_similarity():
    # lexically near-identical, but one asserts the forbidden canonical fact -> conflict dominates
    r = es.classify_evidence_relation("BYON is level 3", "BYON is not level 3")
    assert r["relation"] == es.CANONICAL_CONFLICT
    assert r["method"] == "deterministic_canonical"


def test_claude_nli_advisory_not_authority():
    # advisor disabled by default: its suggestion is ignored entirely
    advisor = lambda a, b: es.CONTRADICTS
    r = es.classify_evidence_relation("I like coffee in the morning",
                                      "The Eiffel Tower is in Paris", claude_advisor=advisor)
    assert r["relation"] == es.UNRELATED and r["method"] != "claude_advisory"
    # even enabled, advisory can NEVER override a canonical conflict
    import os
    os.environ["BYON_EVIDENCE_NLI"] = "true"
    try:
        r2 = es.classify_evidence_relation("BYON is level 3", "BYON is not level 3",
                                           claude_advisor=lambda a, b: es.SAME)
        assert r2["relation"] == es.CANONICAL_CONFLICT
    finally:
        os.environ.pop("BYON_EVIDENCE_NLI", None)


def test_secret_not_classified():
    r = es.classify_evidence_relation("the codeword is mountain", "the codeword is river",
                                      context={"is_secret": True})
    assert r["method"] == "secret_guard" and r["confidence"] == 0.0


# ----------------------------------------------------------------------------
# helpers for lifecycle tests
# ----------------------------------------------------------------------------
class FakeMem:
    def __init__(self):
        self.stored = []

    def store_fact(self, fact, *, source="", tags=None, thread_id=None, trust=None,
                   disputed=None, disputed_pattern=None):
        self.stored.append({"fact": fact, "trust": trust})
        return {"success": True, "ctx_id": len(self.stored)}


def _lc(tmp_path, mem=None):
    return cl.CandidateLifecycle(tmp_path, mem_client=mem, thread_id="u")


def _ingest(lc, task_id, claim, source_class="EXTRACTED_USER_CLAIM", topic="t", status="PROVISIONAL"):
    return lc.ingest_task_result(task_id=task_id, topic=topic, claim=claim,
                                 sources_used=[f"src:{task_id}"], epistemic_status=status,
                                 source_class=source_class, source_event_ids=[f"ev_{task_id}"])


# ----------------------------------------------------------------------------
# T2 — semantic merge / dispute in the lifecycle
# ----------------------------------------------------------------------------
def test_paraphrased_same_claim_merges():
    lc = _lc_tmp()
    _ingest(lc, "t1", "The capital of France is Paris")
    _ingest(lc, "t2", "Paris is the capital of France")
    active = lc.active()
    assert len(active) == 1 and active[0]["evidence_count"] == 2
    assert active[0]["semantic_relation"] == es.SAME


def test_paraphrased_contradiction_creates_challenger():
    lc = _lc_tmp()
    _ingest(lc, "t1", "The server is up")
    ch = _ingest(lc, "t2", "The server is down")
    assert ch["status"] == cl.DISPUTED and ch["challenger_of"] is not None
    assert ch["semantic_relation"] in (es.CONTRADICTS, es.CANONICAL_CONFLICT)


def test_unrelated_same_topic_not_merged():
    lc = _lc_tmp()
    _ingest(lc, "t1", "I like coffee in the morning", topic="t")
    _ingest(lc, "t2", "The Eiffel Tower is in Paris", topic="t")
    active = lc.active()
    assert len(active) == 2 and all(r["evidence_count"] == 1 for r in active)


def test_narrow_claim_links_without_commit():
    lc = _lc_tmp()
    a = _ingest(lc, "t1", "byon uses faiss memory index")
    b = _ingest(lc, "t2", "byon uses memory")
    assert b["semantic_relation"] in (es.NARROWS, es.BROADENS)
    assert a["candidate_id"] in b["related_candidate_ids"]
    assert len(lc.active()) == 2 and all(r["evidence_count"] == 1 for r in lc.active())


def test_broad_claim_requires_more_evidence():
    lc = _lc_tmp(FakeMem())
    _ingest(lc, "t1", "byon uses memory")
    _ingest(lc, "t2", "byon uses faiss memory index ip")
    lc.consolidate()
    assert lc.counts().get(cl.COMMITTED, 0) == 0      # linked, each only 1 evidence -> no commit


# ----------------------------------------------------------------------------
# T3 — evidence quality gate
# ----------------------------------------------------------------------------
def _cand(**kw):
    base = {"evidence_count": 1, "contradiction_count": 0, "source_class": "EXTRACTED_USER_CLAIM",
            "created_ts": time.time(), "confidence": 0.5, "source_keys": ["EXTRACTED_USER_CLAIM::t::s"]}
    base.update(kw)
    return base


def test_two_same_source_evidence_not_enough():
    lc = _lc_tmp(FakeMem())
    _ingest(lc, "t1", "fact alpha beta gamma")
    _ingest(lc, "t1", "fact alpha beta gamma")          # SAME source -> skey dedup, no new evidence
    lc.consolidate()
    assert lc.counts().get(cl.COMMITTED, 0) == 0
    assert lc.active()[0]["evidence_count"] == 1


def test_two_independent_sources_commit():
    lc = _lc_tmp(FakeMem())
    _ingest(lc, "t1", "fact alpha beta gamma")
    _ingest(lc, "t2", "fact alpha beta gamma")          # independent source -> evidence 2
    lc.consolidate()
    assert lc.counts().get(cl.COMMITTED, 0) == 1


def test_verified_source_raises_quality():
    verified = cl.evidence_quality_score(_cand(source_class="DOMAIN_VERIFIED",
                                                source_keys=["DOMAIN_VERIFIED::t::s"]))
    unverified = cl.evidence_quality_score(_cand())
    assert verified > unverified


def test_contradiction_blocks_commit():
    d = cl.evaluate_candidate(_cand(evidence_count=2, contradiction_count=1))
    assert d["action"] != cl.COMMIT


def test_stale_source_lowers_quality():
    fresh = cl.evidence_quality_score(_cand(evidence_count=2))
    stale = cl.evidence_quality_score(_cand(evidence_count=2, created_ts=time.time() - 30 * 86400))
    assert stale < fresh


def test_vault_objective_claim_cannot_commit():
    # a vault/user-grounded claim commits ONLY as USER_PREFERENCE, never as objective truth
    assert cl._commit_trust("USER_MEMORY_GROUNDED") == "USER_PREFERENCE"
    lc = _lc_tmp(FakeMem())
    _ingest(lc, "t1", "world cup winner is france", source_class="USER_MEMORY_GROUNDED")
    _ingest(lc, "t2", "world cup winner is france", source_class="USER_MEMORY_GROUNDED")
    lc.consolidate()
    committed = lc.list(cl.COMMITTED)
    assert committed and committed[0]["trust_tier"] == "USER_PREFERENCE"


# ----------------------------------------------------------------------------
# T4 — dispute explanation
# ----------------------------------------------------------------------------
def test_dispute_record_written():
    lc = _lc_tmp()
    _ingest(lc, "t1", "The server is up")
    _ingest(lc, "t2", "The server is down")
    disputes = lc.list_disputes()
    assert disputes and {"candidate_id", "challenger_id", "relation", "reason",
                         "required_next_step"} <= set(disputes[0])


def test_disputed_answer_explains_conflict():
    lc = _lc_tmp()
    _ingest(lc, "t1", "The server is up")
    _ingest(lc, "t2", "The server is down")
    d = lc.list_disputes()[0]
    assert d["evidence_a"] and d["evidence_b"] and d["reason"]


def test_canonical_conflict_explains_override():
    lc = _lc_tmp()
    _ingest(lc, "t1", "BYON is level 3")
    _ingest(lc, "t2", "BYON is not level 3")
    d = lc.list_disputes()[0]
    assert d["relation"] == es.CANONICAL_CONFLICT and d["required_next_step"] == "canonical_overrides"


def test_user_claim_conflict_asks_for_source():
    lc = _lc_tmp()
    _ingest(lc, "t1", "The server is up", source_class="EXTRACTED_USER_CLAIM")
    _ingest(lc, "t2", "The server is down", source_class="EXTRACTED_USER_CLAIM")
    d = lc.list_disputes()[0]
    assert d["required_next_step"] == "ask_user_for_source"


# ----------------------------------------------------------------------------
# tmp-path shim (pytest tmp_path injected per-test would need fixtures; use tmpdir factory)
# ----------------------------------------------------------------------------
import tempfile


def _lc_tmp(mem=None):
    d = tempfile.mkdtemp()
    return cl.CandidateLifecycle(d, mem_client=mem, thread_id="u")
