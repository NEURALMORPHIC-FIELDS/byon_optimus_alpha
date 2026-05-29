# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 15 TRACK G - grounded path explanation v2 (built on the per-hop path score)."""
from __future__ import annotations

from gateway.relation_field import COMMITTED, RelationField
from gateway.relation_reports import render_path_explanation_v2


def _field(tmp_path):
    return RelationField(str(tmp_path))


def _committed(f, s, p, o, sid):
    f.add_relation(s, p, o, source_id=sid, source_class="VERIFIED_PROJECT_FACT", status=COMMITTED,
                   origin="canonical_schema", evidence_quote=f"{s} {p} {o}")


def _known_path(tmp_path):
    f = _field(tmp_path)
    _committed(f, "BYON", "has_component", "D_Cortex", "rel:1")
    _committed(f, "D_Cortex", "has_component", "FAISS", "rel:2")
    return render_path_explanation_v2(f, "BYON", "FAISS")


def test_path_v2_explains_bottleneck(tmp_path):
    v2 = _known_path(tmp_path)
    assert v2["found"] is True
    assert v2["bottleneck"] is not None
    assert "explanation" in v2["bottleneck"] and "index" in v2["bottleneck"]


def test_path_v2_explains_known_status(tmp_path):
    v2 = _known_path(tmp_path)
    assert v2["epistemic_status"] == "KNOWN"
    assert v2["why"]
    assert "KNOWN" in v2["path_summary"]


def test_path_v2_explains_provisional_status(tmp_path):
    f = _field(tmp_path)
    f.add_relation("BYON", "depends_on", "SomethingX", source_id="rel:3",
                   source_class="EXTRACTED_USER_CLAIM")     # default status -> candidate
    v2 = render_path_explanation_v2(f, "BYON", "SomethingX")
    assert v2["found"] is True
    assert v2["epistemic_status"] == "PROVISIONAL"


def test_path_v2_explains_disputed_status(tmp_path):
    f = _field(tmp_path)
    f.add_relation("BYON", "contradicts", "ClaimY", source_id="rel:4",
                   source_class="EXTRACTED_USER_CLAIM", is_contradiction=True)
    v2 = render_path_explanation_v2(f, "BYON", "ClaimY")
    assert v2["found"] is True
    assert v2["epistemic_status"] == "DISPUTED"


def test_weak_path_recommends_next_action(tmp_path):
    f = _field(tmp_path)
    f.add_relation("BYON", "depends_on", "WeakThing", source_id="rel:5",
                   source_class="EXTRACTED_USER_CLAIM")     # candidate -> weak
    v2 = render_path_explanation_v2(f, "BYON", "WeakThing")
    assert v2["next_recommended_action"]                    # weak path must recommend an action


def test_path_v2_includes_source_per_hop(tmp_path):
    v2 = _known_path(tmp_path)
    assert v2["hops"]
    for h in v2["hops"]:
        assert "source" in h and "source_classes" in h and "source_ids" in h
