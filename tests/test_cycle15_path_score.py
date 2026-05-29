# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 15 TRACK F - per-hop path weighting (pure, load-free; builds path dicts directly)."""
from __future__ import annotations

from gateway.relation_path_score import PROVISIONAL, path_score
from gateway.relation_field import CANDIDATE, COMMITTED, DISPUTED


def hop(w, *, status=COMMITTED, decay="fresh", inverse=False,
        sc=("VERIFIED_PROJECT_FACT",), conf=None, contra=0):
    return {"subject": "A", "relation_type": "has_component", "object": "B", "status": status,
            "decayed_weight": w, "weight": w, "confidence": (w if conf is None else conf),
            "decay_status": decay, "inverse_rendered": inverse, "source_classes": list(sc),
            "contradiction_count": contra}


def path(hops, *, canonical=False):
    return {"hops": hops, "canonical": canonical}


def test_path_weight_uses_per_hop_scores():
    a = path_score(path([hop(0.9), hop(0.5)]))      # avg 0.7
    b = path_score(path([hop(0.5), hop(0.5)]))      # same MIN 0.5, avg 0.5
    assert a["edge_weights"] == [0.9, 0.5]
    assert a["path_weight"] > b["path_weight"]      # combined per-hop, not the min edge


def test_bottleneck_edge_reported():
    s = path_score(path([hop(0.9), hop(0.3), hop(0.7)]))
    assert s["bottleneck_edge"]["index"] == 1
    assert s["bottleneck_edge"]["weight"] == 0.3


def test_disputed_edge_penalizes_path():
    clean = path_score(path([hop(0.8), hop(0.8)]))
    disp = path_score(path([hop(0.8), hop(0.8, status=DISPUTED)]))
    assert disp["status_penalty"] > 0
    assert disp["path_weight"] < clean["path_weight"]
    assert disp["path_status"] == DISPUTED


def test_candidate_edge_makes_path_provisional():
    s = path_score(path([hop(0.8), hop(0.7, status=CANDIDATE)]))
    assert s["path_status"] == PROVISIONAL


def test_decayed_edge_lowers_path_score():
    fresh = path_score(path([hop(0.8, decay="fresh"), hop(0.8, decay="fresh")]))
    decayed = path_score(path([hop(0.8, decay="fresh"), hop(0.8, decay="stale")]))
    assert decayed["decay_penalty"] > 0
    assert decayed["path_weight"] < fresh["path_weight"]


def test_inverse_edge_lowers_path_score():
    normal = path_score(path([hop(0.8), hop(0.8)]))
    inv = path_score(path([hop(0.8), hop(0.8, inverse=True)]))
    assert inv["source_policy_penalty"] > 0
    assert inv["path_weight"] < normal["path_weight"]


def test_canonical_path_scores_high():
    s = path_score(path([hop(0.85), hop(0.85)], canonical=True))
    assert s["canonical"] is True
    assert s["path_weight"] >= 0.6


def test_longer_path_penalized():
    short = path_score(path([hop(0.8), hop(0.8)]))
    longer = path_score(path([hop(0.8), hop(0.8), hop(0.8), hop(0.8)]))
    assert longer["length_penalty"] > short["length_penalty"]
    assert longer["path_weight"] < short["path_weight"]
