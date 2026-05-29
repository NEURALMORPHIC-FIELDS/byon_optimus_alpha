# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 15 TRACK B - scheduled relation decay maintenance (never deletes, never commits)."""
from __future__ import annotations

import time

from gateway.relation_field import COMMITTED, RelationField, relation_decay
from gateway.relation_maintenance import run_relation_decay_maintenance

FUTURE = time.time() + 90 * 86400          # age every relation by ~90 days


def _field(tmp_path):
    f = RelationField(str(tmp_path / "rf"))
    f.add_relation("BYON", "has_component", "D_Cortex", source_id="r:c",
                   source_class="VERIFIED_PROJECT_FACT", status=COMMITTED,
                   origin="canonical_schema", evidence_quote="canonical")
    f.add_relation("Alpha", "depends_on", "Beta", source_id="r:m1",
                   source_class="DOMAIN_VERIFIED", status=COMMITTED, evidence_quote="committed")
    f.add_relation("Alpha", "depends_on", "Beta", source_id="r:m2",
                   source_class="DOMAIN_VERIFIED", status=COMMITTED)
    f.add_relation("Gamma", "contradicts", "Delta", source_id="r:d",
                   source_class="EXTRACTED_USER_CLAIM", is_contradiction=True)
    f.add_relation("Eps", "depends_on", "Zeta", source_id="r:cand",
                   source_class="EXTRACTED_USER_CLAIM")
    return f


def _run(tmp_path, f):
    return run_relation_decay_maintenance(f, log_path=str(tmp_path / "maint.jsonl"), now_ts=FUTURE)


def test_scheduled_decay_scans_relations(tmp_path):
    f = _field(tmp_path)
    rep = _run(tmp_path, f)
    assert rep["relations_scanned"] == 4          # 4 distinct relations (Alpha->Beta deduped)


def test_canonical_relation_resists_scheduled_decay(tmp_path):
    f = _field(tmp_path)
    rep = _run(tmp_path, f)
    assert rep["canonical_resisted_decay"] >= 1
    canon = f._rel[next(k for k, r in f._rel.items() if r["subject"] == "BYON")]
    assert relation_decay(canon, now_ts=FUTURE)["decay_factor"] >= 0.99


def test_disputed_relation_decays_faster_in_maintenance(tmp_path):
    f = _field(tmp_path)
    rep = _run(tmp_path, f)
    assert rep["disputed_decayed"] >= 1
    disp = next(r for r in f._rel.values() if r["subject"] == "Gamma")
    comm = next(r for r in f._rel.values() if r["subject"] == "Alpha")
    assert relation_decay(disp, now_ts=FUTURE)["decayed_weight"] < \
        relation_decay(comm, now_ts=FUTURE)["decayed_weight"]


def test_scheduled_decay_does_not_delete_relation(tmp_path):
    f = _field(tmp_path)
    before = len(f._rel)
    _run(tmp_path, f)
    assert len(f._rel) == before == 4             # decay never deletes


def test_maintenance_log_written(tmp_path):
    f = _field(tmp_path)
    _run(tmp_path, f)
    log = tmp_path / "maint.jsonl"
    assert log.exists() and log.read_text(encoding="utf-8").strip()


def test_maintenance_idempotent(tmp_path):
    f = _field(tmp_path)
    r1 = _run(tmp_path, f)
    r2 = _run(tmp_path, f)
    assert r1["relations_scanned"] == r2["relations_scanned"] == 4
    assert len(f._rel) == 4                        # still no deletion after a second pass


def test_weak_relations_flagged_by_decay(tmp_path):
    f = _field(tmp_path)
    rep = _run(tmp_path, f)
    flagged = {x["subject"] for x in rep["weak_relations_flagged"]}
    assert "Gamma" in flagged and "Eps" in flagged   # disputed + candidate flagged weak
