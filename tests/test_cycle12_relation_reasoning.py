"""Cycle 12 - directed, evidence-weighted, source-policy-aware relational reasoning.

S1 directed semantics, S2 evidence-weighted ranking, S3 relation-type source policy, S4 relation-
aware normal answering, S5 contradiction classification, S6 relation-aware self-state. The relation
field stays non-authoritative; source policy + the Auditor remain dominant.
"""
from __future__ import annotations

import importlib
import time

import pytest

pytest.importorskip("httpx")

rf = importlib.import_module("gateway.relation_field")
rp = importlib.import_module("gateway.relation_policy")
rr = importlib.import_module("gateway.relation_reports")


def _f(tmp_path):
    return rf.RelationField(tmp_path)


def _add(f, s, p, o, *, sc="VERIFIED_PROJECT_FACT", rtype=None, sid=None, status=None,
         origin="inferred", contra=False):
    return f.add_relation(s, p, o, relation_type=rtype, source_id=sid or f"{s}-{o}",
                          source_class=sc, status=status, origin=origin, is_contradiction=contra)


# ============================================================ S1 - directed semantics
def test_has_component_direction_forward_only(tmp_path):
    f = _f(tmp_path)
    _add(f, "A", "has_component", "B", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL")
    assert f.multi_hop_path("A", "B", max_depth=2)["paths"]
    assert f.multi_hop_path("B", "A", max_depth=2)["paths"] == []


def test_depends_on_direction_enforced(tmp_path):
    f = _f(tmp_path)
    _add(f, "A", "depends_on", "B", rtype=rf.DEPENDS_ON, sc="SYSTEM_CANONICAL")
    assert f.multi_hop_path("A", "B", max_depth=2)["paths"]
    assert f.multi_hop_path("B", "A", max_depth=2)["paths"] == []


def test_contradicts_bidirectional(tmp_path):
    f = _f(tmp_path)
    _add(f, "X", "contradicts", "Y", rtype=rf.CONTRADICTS, contra=True)
    assert f.multi_hop_path("X", "Y", max_depth=2)["paths"]
    assert f.multi_hop_path("Y", "X", max_depth=2)["paths"]


def test_inverse_rendering_not_truth(tmp_path):
    f = _f(tmp_path)
    _add(f, "A", "broader_than", "B", rtype=rf.BROADER_THAN, sc="SYSTEM_CANONICAL")
    p = f.multi_hop_path("B", "A", max_depth=2, include_inverse=True)["paths"]
    hop = p[0]["hops"][0]
    assert hop["inverse_rendered"] and hop["relation_type"] == rf.NARROWER_THAN
    assert not any(r["relation_type"] == rf.NARROWER_THAN for r in f._rel.values())  # not stored


def test_multi_hop_respects_direction(tmp_path):
    f = _f(tmp_path)
    _add(f, "A", "has_component", "B", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL")
    _add(f, "B", "has_component", "C", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL")
    assert f.multi_hop_path("A", "C", max_depth=2)["paths"][0]["length"] == 2
    assert f.multi_hop_path("C", "A", max_depth=2)["paths"] == []


def test_include_inverse_allows_rendered_inverse_with_warning(tmp_path):
    f = _f(tmp_path)
    _add(f, "A", "broader_than", "B", rtype=rf.BROADER_THAN, sc="SYSTEM_CANONICAL")
    assert f.multi_hop_path("B", "A", max_depth=2)["paths"] == []
    res = f.multi_hop_path("B", "A", max_depth=2, include_inverse=True)["paths"]
    assert res and res[0]["inverse_rendered"] and "inverse" in (res[0]["note"] or "").lower()


# ============================================================ S2 - evidence-weighted ranking
def _rel(**kw):
    base = {"relation_type": rf.DEPENDS_ON, "status": rf.CANDIDATE, "source_classes": ["DOMAIN_VERIFIED"],
            "source_ids": ["s1"], "confidence": 0.7, "origin": "inferred",
            "last_seen": rf._now(), "first_seen": rf._now()}
    base.update(kw)
    return base


def test_canonical_relation_ranks_above_vault(tmp_path):
    f = _f(tmp_path)
    _add(f, "Topic", "mentioned_in", "vault", rtype=rf.MENTIONED_IN, sc="EXTRACTED_USER_CLAIM")
    _add(f, "BYON", "has_component", "Topic", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL",
         status=rf.COMMITTED)
    assert "SYSTEM_CANONICAL" in f.relations_for("Topic")[0]["source_classes"]


def test_committed_relation_ranks_above_candidate():
    committed = _rel(status=rf.COMMITTED, source_classes=["VERIFIED_PROJECT_FACT"])
    candidate = _rel(status=rf.CANDIDATE, source_classes=["EXTRACTED_USER_CLAIM"])
    assert rf.relation_weight_score(committed) > rf.relation_weight_score(candidate)


def test_disputed_relation_penalized_but_visible(tmp_path):
    f = _f(tmp_path)
    committed = _rel(status=rf.COMMITTED, source_classes=["SYSTEM_CANONICAL"])
    disputed = _rel(status=rf.DISPUTED, contradiction_count=1)
    assert rf.relation_weight_score(disputed) < rf.relation_weight_score(committed)
    _add(f, "X", "contradicts", "Y", rtype=rf.CONTRADICTS, contra=True)
    assert f.contradictions()                                     # still visible


def test_evidence_count_increases_weight():
    one = _rel(source_ids=["s1"])
    two = _rel(source_ids=["s1", "s2"])
    assert rf.relation_weight_score(two) > rf.relation_weight_score(one)


def test_stale_source_reduces_weight():
    fresh = _rel(last_seen=rf._now())
    stale = _rel(last_seen="2025-01-01T00:00:00Z")
    assert rf.relation_weight_score(stale) < rf.relation_weight_score(fresh)


def test_path_ranking_uses_edge_weights(tmp_path):
    f = _f(tmp_path)
    _add(f, "A", "has_component", "M", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL", sid="c1")
    _add(f, "M", "has_component", "Z", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL", sid="c2")
    _add(f, "A", "mentioned_in", "V", rtype=rf.MENTIONED_IN, sc="EXTRACTED_USER_CLAIM", sid="v1")
    _add(f, "V", "mentioned_in", "Z", rtype=rf.MENTIONED_IN, sc="EXTRACTED_USER_CLAIM", sid="v2")
    paths = f.multi_hop_path("A", "Z", max_depth=2)["paths"]
    assert paths[0]["canonical"] is True and paths[0]["weight"] >= paths[-1]["weight"]


# ============================================================ S3 - relation-type source policy
def test_architecture_has_component_requires_project_source():
    assert rp.commit_allowed(rf.HAS_COMPONENT, ["EXTRACTED_USER_CLAIM"], subject="BYON")[0] is False
    assert rp.commit_allowed(rf.HAS_COMPONENT, ["VERIFIED_PROJECT_FACT"], subject="BYON")[0] is True


def test_user_prefers_allows_user_preference():
    assert rp.commit_allowed(rf.USER_PREFERS, ["USER_PREFERENCE"])[0] is True


def test_mentioned_in_allows_vault_memory():
    assert rp.commit_allowed(rf.MENTIONED_IN, ["USER_MEMORY_GROUNDED"])[0] is True


def test_objective_depends_on_requires_verified_source():
    assert rp.commit_allowed(rf.DEPENDS_ON, ["EXTRACTED_USER_CLAIM"])[0] is False
    assert rp.commit_allowed(rf.DEPENDS_ON, ["DOMAIN_VERIFIED"])[0] is True


def test_vault_depends_on_not_objective_truth(tmp_path):
    f = _f(tmp_path)
    for s in ("s1", "s2"):
        f.ingest_candidate_relation({"subject": "Zeta", "predicate": "depends on", "object": "Theta",
                                     "relation_type": rf.DEPENDS_ON, "source_id": s,
                                     "source_class": "EXTRACTED_USER_CLAIM"})
    f.consolidate()
    assert f.relations_for("Zeta")[0]["status"] != rf.COMMITTED


def test_relation_policy_blocks_unsafe_commit():
    assert rp.commit_allowed(rf.DEPENDS_ON, ["DISPUTED_OR_UNSAFE"])[0] is False


# ============================================================ S4 - relation-aware normal answering
def _arch_field(tmp_path):
    f = _f(tmp_path)
    _add(f, "BYON", "has_component", "D_Cortex", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL",
         status=rf.COMMITTED, origin="canonical_schema")
    _add(f, "BYON", "has_component", "FCE-M", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL",
         status=rf.COMMITTED, origin="canonical_schema")
    return f


def test_normal_answer_uses_relation_context(tmp_path):
    ctx = rr.relation_context_for(_arch_field(tmp_path), "ce rol are BYON in sistem?")
    assert ctx["relations"] and ctx["focus"]


def test_relation_context_included_with_sources(tmp_path):
    ctx = rr.relation_context_for(_arch_field(tmp_path), "ce rol are BYON?")
    assert ctx["sources"] and "relation:field" in ctx["sources"]


def test_relation_context_blocked_if_source_policy_disallows(tmp_path):
    f = _arch_field(tmp_path)
    # a vault-only OBJECTIVE depends_on must not be presented as objective architecture context
    _add(f, "BYON", "depends_on", "SecretSauce", rtype=rf.DEPENDS_ON, sc="EXTRACTED_USER_CLAIM",
         status=rf.REINFORCED)
    ctx = rr.relation_context_for(f, "ce rol are BYON?")
    assert ctx["blocked_count"] >= 1
    assert all("SecretSauce" not in b["object"] for b in ctx["relations"])


def test_relation_field_not_used_for_secret(tmp_path):
    ctx = rr.relation_context_for(_arch_field(tmp_path), "what is my password?", is_secret=True)
    assert ctx["blocked"] is True and ctx["relations"] == []


def test_relation_context_does_not_override_memory_fact(tmp_path):
    hits = rr.relation_context_hits(_arch_field(tmp_path), "BYON D_Cortex")
    # context hits are clearly relational (source 'relation:...'), additive to memory facts
    assert hits and all(h["metadata"]["source"].startswith("relation:") for h in hits)


def test_relation_context_improves_architecture_answer(tmp_path):
    ctx = rr.relation_context_for(_arch_field(tmp_path), "ce rol are D_Cortex?")
    assert any(b["relation_type"] == rf.HAS_COMPONENT for b in ctx["relations"])


# ============================================================ S5 - contradiction classification
def test_canonical_conflict_classified(tmp_path):
    f = _f(tmp_path)
    r = _add(f, "BYON", "is", "level 3", rtype=rf.CONTRADICTS, sc="EXTRACTED_USER_CLAIM", contra=True)
    assert f.classify_conflict(r) == "canonical_conflict"


def test_temporal_conflict_classified(tmp_path):
    f = _f(tmp_path)
    r = _add(f, "Alpha", "depends_on", "Beta", rtype=rf.DEPENDS_ON, sc="DOMAIN_VERIFIED")
    r["first_seen"] = "2025-01-01T00:00:00Z"
    r["contradicted_at"] = "2026-01-01T00:00:00Z"
    r["contradiction_count"] = 1
    assert f.classify_conflict(r) == "temporal_conflict"


def test_source_scope_conflict_classified(tmp_path):
    f = _f(tmp_path)
    r = _add(f, "Gamma", "depends_on", "Delta", rtype=rf.DEPENDS_ON, sc="EXTRACTED_USER_CLAIM",
             contra=True)
    r["source_classes"] = ["EXTRACTED_USER_CLAIM", "VERIFIED_PROJECT_FACT"]
    assert f.classify_conflict(r) == "source_scope_conflict"


def test_contradiction_answer_explains_conflict_type(tmp_path):
    f = _f(tmp_path)
    _add(f, "BYON", "is", "level 3", rtype=rf.CONTRADICTS, sc="EXTRACTED_USER_CLAIM", contra=True)
    out = rr.render_answer(f, "ce contradictii exista in jurul BYON?")
    assert "conflict" in out["answer"].lower()


def test_older_vault_note_does_not_override_newer_canonical(tmp_path):
    f = _f(tmp_path)
    canon = _add(f, "BYON", "operational_level", "Level 2", rtype=rf.ROLE_OF, sc="SYSTEM_CANONICAL",
                 status=rf.COMMITTED, origin="canonical_schema")
    vault = _rel(status=rf.DISPUTED, source_classes=["EXTRACTED_USER_CLAIM"], last_seen="2025-01-01T00:00:00Z")
    assert rf.relation_weight_score(canon) > rf.relation_weight_score(vault)


# ============================================================ S6 - relation-aware self-state
def _metric_field(tmp_path):
    f = _f(tmp_path)
    _add(f, "BYON", "has_component", "D_Cortex", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL",
         status=rf.COMMITTED)
    _add(f, "BYON", "has_component", "FCE-M", rtype=rf.HAS_COMPONENT, sc="SYSTEM_CANONICAL",
         status=rf.COMMITTED)
    _add(f, "BYON", "depends_on", "memory-service", rtype=rf.DEPENDS_ON, sc="VERIFIED_PROJECT_FACT")
    return f


def test_central_concepts_report(tmp_path):
    rows = _metric_field(tmp_path).central_concepts(5)
    assert rows and rows[0]["name"].lower() == "byon" and "weighted_centrality" in rows[0]


def test_top_disputed_areas_report(tmp_path):
    f = _metric_field(tmp_path)
    _add(f, "BYON", "contradicts", "ghost claim", rtype=rf.CONTRADICTS, contra=True)
    assert f.disputed_areas(5)


def test_recently_reinforced_relations_report(tmp_path):
    f = _f(tmp_path)
    f.add_relation("P", "depends_on", "Q", source_id="s1", source_class="VERIFIED_PROJECT_FACT")
    f.add_relation("P", "depends_on", "Q", source_id="s2", source_class="VERIFIED_PROJECT_FACT")
    assert f.recently_reinforced(5)


def test_candidate_relations_report(tmp_path):
    f = _f(tmp_path)
    f.ingest_candidate_relation({"subject": "P", "predicate": "depends on", "object": "Q",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "s1",
                                 "source_class": "EXTRACTED_USER_CLAIM"})
    assert f.candidate_relations(5)


def test_self_state_uses_relation_metrics(tmp_path):
    m = _metric_field(tmp_path).relation_metrics()
    assert {"central_concepts", "disputed_areas", "active_candidate_relations",
            "source_class_mix"} <= set(m)
