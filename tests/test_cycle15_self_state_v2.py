# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 15 TRACK H - relation-aware self-state v2 (read-only aggregation; never truth authority)."""
from __future__ import annotations

from gateway.relation_field import RelationField
from gateway.relation_maintenance import run_relation_decay_maintenance
from gateway.relation_reports import relation_self_state_v2
from gateway.relation_task_results import ingest_relation_task_result


def _setup(tmp_path):
    f = RelationField(str(tmp_path / "rf"))
    # central + weak hub with candidate relations, and a 2-hop candidate path Hub->A->C
    f.add_relation("Hub", "depends_on", "A", source_id="r1", source_class="EXTRACTED_USER_CLAIM")
    f.add_relation("Hub", "depends_on", "B", source_id="r2", source_class="EXTRACTED_USER_CLAIM")
    f.add_relation("A", "depends_on", "C", source_id="r3", source_class="EXTRACTED_USER_CLAIM")
    maint_log = str(tmp_path / "maint.jsonl")
    results_log = str(tmp_path / "results.jsonl")
    run_relation_decay_maintenance(f, log_path=maint_log)
    ingest_relation_task_result(
        gap={"relation_id": "r1", "subject": "Hub", "object": "A", "gap_type": "find_internal_evidence",
             "predicate": "depends_on"},
        result={"epistemic_status": "PROVISIONAL", "answer_summary": "evidence", "sources_used": ["memory"]},
        field=f, log_path=results_log)
    return f, maint_log, results_log


def _state(tmp_path):
    f, maint_log, results_log = _setup(tmp_path)
    return relation_self_state_v2(f, maintenance_log_path=maint_log, task_results_log_path=results_log)


def test_self_state_reports_relation_maintenance(tmp_path):
    st = _state(tmp_path)
    assert st["relation_maintenance"] is not None
    assert "relations_scanned" in st["relation_maintenance"]


def test_self_state_reports_gap_repair_tasks(tmp_path):
    st = _state(tmp_path)
    assert isinstance(st["gaps_found"], list) and st["gaps_found"]


def test_self_state_reports_auto_repaired_relations(tmp_path):
    st = _state(tmp_path)
    assert st["relations_auto_repaired"]                      # the ingested result reinforced a relation


def test_self_state_reports_weak_paths(tmp_path):
    st = _state(tmp_path)
    assert isinstance(st["weak_paths"], list) and st["weak_paths"]
    assert "path_weight" in st["weak_paths"][0]


def test_self_state_reports_central_nodes_needing_sources(tmp_path):
    st = _state(tmp_path)
    assert isinstance(st["central_nodes_needing_sources"], list)
    assert st["central_nodes_needing_sources"]
    assert st["is_truth_authority"] is False and st["answers_user_directly"] is False
