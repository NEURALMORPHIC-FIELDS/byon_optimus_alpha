# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 15 TRACK E - relation gap-repair task-result ingestion (candidate lifecycle, never commit)."""
from __future__ import annotations

from gateway.relation_field import DISPUTED, RelationField
from gateway.relation_task_results import ingest_relation_task_result, read_relation_task_results


class FakeLifecycle:
    def __init__(self):
        self.ingested = []
        self.committed = []

    def ingest_task_result(self, **kw):
        self.ingested.append(kw)
        return {"candidate_id": "cand_1", "state": "candidate"}

    def commit(self, *a, **k):                       # must NEVER be called by ingestion
        self.committed.append((a, k))


GAP = {"relation_id": "rid1", "subject": "Alpha", "object": "Beta",
       "gap_type": "find_internal_evidence", "predicate": "depends_on", "topic": "relgap:rid1"}


def _log(tmp_path):
    return str(tmp_path / "relation_task_results.jsonl")


def test_relation_task_result_logged(tmp_path):
    row = ingest_relation_task_result(
        gap=GAP, result={"epistemic_status": "PROVISIONAL", "answer_summary": "found internal evidence"},
        lifecycle=FakeLifecycle(), log_path=_log(tmp_path))
    rows = read_relation_task_results(_log(tmp_path))
    assert rows and rows[-1]["task_type"] == "find_internal_evidence"
    for k in ("task_id", "gap_id", "relation_id", "evidence_found", "candidate_created",
              "epistemic_status", "result_summary", "timestamp"):
        assert k in row


def test_evidence_task_creates_candidate(tmp_path):
    lc = FakeLifecycle()
    row = ingest_relation_task_result(
        gap=GAP, result={"epistemic_status": "PROVISIONAL", "answer_summary": "evidence",
                         "sources_used": ["memory"]},
        lifecycle=lc, log_path=_log(tmp_path))
    assert row["evidence_found"] is True
    assert row["candidate_created"] is True and row["candidate_id"] == "cand_1"
    assert lc.ingested                                # routed through the candidate lifecycle


def test_contradiction_task_creates_disputed_challenger(tmp_path):
    f = RelationField(str(tmp_path / "rf"))
    ingest_relation_task_result(
        gap=GAP, result={"epistemic_status": "DISPUTED", "answer_summary": "contradicting evidence"},
        field=f, log_path=_log(tmp_path))
    challengers = [r for r in f._rel.values()
                   if r["subject"] == "Alpha" and r["object"] == "Beta"
                   and (r.get("contradiction_count", 0) > 0 or r.get("status") == DISPUTED)]
    assert challengers, "a disputed challenger relation must be created"


def test_no_evidence_task_does_not_fabricate(tmp_path):
    lc = FakeLifecycle()
    row = ingest_relation_task_result(
        gap=GAP, result={"epistemic_status": "UNKNOWN", "answer_summary": ""},
        lifecycle=lc, log_path=_log(tmp_path))
    assert row["evidence_found"] is False
    assert row["candidate_created"] is False
    assert not lc.ingested                            # nothing stored
    assert "unresolved" in row["result_summary"]      # honest, not fabricated


def test_task_result_never_commits_directly(tmp_path):
    lc = FakeLifecycle()
    row = ingest_relation_task_result(
        gap=GAP, result={"epistemic_status": "KNOWN", "answer_summary": "strong evidence",
                         "sources_used": ["memory", "project_file"]},
        lifecycle=lc, log_path=_log(tmp_path))
    assert row["committed_directly"] is False
    assert lc.committed == []                          # commit path never invoked by ingestion


def test_fce_priority_not_truth(tmp_path):
    lc = FakeLifecycle()
    row = ingest_relation_task_result(
        gap=GAP, result={"epistemic_status": "KNOWN", "answer_summary": "high fce priority",
                         "fce_priority": 0.99, "sources_used": ["memory"]},
        lifecycle=lc, log_path=_log(tmp_path))
    # even a high-priority KNOWN result is stored as a CANDIDATE, never committed by FCE priority
    assert row["candidate_created"] is True
    assert row["committed_directly"] is False
    assert "priority_only" in row["fce_influence"]
    assert lc.committed == []
