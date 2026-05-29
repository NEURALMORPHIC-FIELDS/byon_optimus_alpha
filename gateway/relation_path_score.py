# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Per-hop path weighting (Cycle 15 TRACK F).

Replaces the old min-edge-weight path score with a per-hop combined score that reads EVERY hop:
its decayed weight, its epistemic status, its decay condition, its source classes, and whether the
hop was inverse-rendered. Pure and load-free: it scores a path object (the dict shape produced by
RelationField._path_obj, with a `hops` list) and makes NO memory-service calls. The relation field
is never a truth authority; this only ranks/explains paths, it never commits anything.

The path STATUS is the weakest epistemic condition along the chain: any disputed hop -> DISPUTED;
else any non-committed (candidate) hop -> provisional; else committed (canonical if every hop is
canonical). The bottleneck edge (weakest hop) is always exposed.
"""
from __future__ import annotations

from typing import Any, Dict, List

from gateway.relation_field import CANDIDATE, COMMITTED, DISPUTED, REINFORCED

PROVISIONAL = "provisional"
_COMMITTED_LIKE = {COMMITTED, REINFORCED}
_VERIFIED_CLASSES = {"SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT", "DOMAIN_VERIFIED"}


def _hop_weight(hop: Dict[str, Any]) -> float:
    """Effective per-hop weight: the decayed weight if present, else the raw weight."""
    w = hop.get("decayed_weight")
    if w is None:
        w = hop.get("weight", 0.0)
    try:
        return max(0.0, min(1.0, float(w)))
    except (TypeError, ValueError):
        return 0.0


def _hop_confidence(hop: Dict[str, Any]) -> float:
    c = hop.get("confidence")
    if c is None:
        c = _hop_weight(hop)
    try:
        return max(0.0, min(1.0, float(c)))
    except (TypeError, ValueError):
        return 0.0


def path_score(path: Dict[str, Any]) -> Dict[str, Any]:
    """Score a path object per-hop. Returns path_weight, edge_weights, bottleneck_edge,
    average_weight, confidence_product, status_penalty, decay_penalty, source_policy_penalty,
    length_penalty, path_status, and a human explanation. Never the min edge alone."""
    hops: List[Dict[str, Any]] = path.get("hops", []) or []
    n = len(hops)
    if n == 0:
        return {"path_weight": 0.0, "edge_weights": [], "bottleneck_edge": None,
                "average_weight": 0.0, "confidence_product": 0.0, "status_penalty": 0.0,
                "decay_penalty": 0.0, "source_policy_penalty": 0.0, "length_penalty": 0.0,
                "path_status": PROVISIONAL, "length": 0,
                "explanation": "empty path (no hops to score)"}

    edge_weights = [round(_hop_weight(h), 4) for h in hops]
    confidences = [_hop_confidence(h) for h in hops]
    average_weight = round(sum(edge_weights) / n, 4)
    confidence_product = 1.0
    for c in confidences:
        confidence_product *= c
    confidence_product = round(confidence_product, 4)

    b_index = min(range(n), key=lambda i: edge_weights[i])
    bh = hops[b_index]
    bottleneck_edge = {"index": b_index, "subject": bh.get("subject"),
                       "relation_type": bh.get("relation_type"), "object": bh.get("object"),
                       "weight": edge_weights[b_index], "status": bh.get("status"),
                       "decay_status": bh.get("decay_status"),
                       "why": "lowest-weighted hop on the path (the chain is only as strong here)"}

    statuses = [h.get("status") for h in hops]
    any_disputed = any(s == DISPUTED for s in statuses) or any(
        int(h.get("contradiction_count", 0) or 0) > 0 for h in hops)
    any_candidate = any(s == CANDIDATE for s in statuses)
    all_committed = all(s in _COMMITTED_LIKE for s in statuses)
    canonical = bool(path.get("canonical")) and all_committed

    status_penalty = 0.6 if any_disputed else (0.25 if any_candidate else
                                               (0.0 if all_committed else 0.12))

    decaying = sum(1 for h in hops if h.get("decay_status") == "decaying")
    stale = sum(1 for h in hops if h.get("decay_status") == "stale")
    decay_penalty = round(min(0.6, 0.08 * decaying + 0.18 * stale), 4)

    inverse_hops = sum(1 for h in hops if h.get("inverse_rendered"))
    mismatch = sum(1 for h in hops
                   if not (set(h.get("source_classes") or []) & _VERIFIED_CLASSES))
    source_policy_penalty = round(min(0.5, 0.12 * inverse_hops + 0.06 * mismatch), 4)

    length_penalty = round(min(0.4, 0.06 * (n - 1)), 4)

    path_weight = round(max(0.0, average_weight * (1 - status_penalty) * (1 - decay_penalty)
                            * (1 - source_policy_penalty) * (1 - length_penalty)), 4)

    if any_disputed:
        path_status = DISPUTED
    elif any_candidate or not all_committed:
        path_status = PROVISIONAL
    else:
        path_status = COMMITTED

    parts = [f"{n} hop(s); average per-hop weight {average_weight}; bottleneck at hop {b_index} "
             f"(weight {edge_weights[b_index]})"]
    if status_penalty:
        parts.append(f"status penalty {status_penalty} ("
                     + ("disputed hop" if any_disputed else
                        ("candidate hop" if any_candidate else "non-committed hop")) + ")")
    if decay_penalty:
        parts.append(f"decay penalty {decay_penalty} ({decaying} decaying, {stale} stale)")
    if source_policy_penalty:
        parts.append(f"source/policy penalty {source_policy_penalty} ({inverse_hops} inverse-rendered, "
                     f"{mismatch} unverified-source hop(s))")
    if length_penalty:
        parts.append(f"length penalty {length_penalty}")
    parts.append(f"path status {path_status}" + (" (canonical)" if canonical else ""))

    return {"path_weight": path_weight, "edge_weights": edge_weights,
            "bottleneck_edge": bottleneck_edge, "bottleneck_index": b_index,
            "average_weight": average_weight, "confidence_product": confidence_product,
            "status_penalty": status_penalty, "decay_penalty": decay_penalty,
            "source_policy_penalty": source_policy_penalty, "length_penalty": length_penalty,
            "path_status": path_status, "canonical": canonical, "length": n,
            "explanation": "; ".join(parts)}
