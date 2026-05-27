"""Cycle 13 — general objective relation-aware answering + trust decay + grounded path explanation
+ contradiction evolution + relation-gap tasks + relation-aware self-state + answer safety metadata.

The relation field stays non-authoritative; decay never deletes; vault-only objective relations
never become objective truth; source policy + the Auditor remain dominant.
"""
from __future__ import annotations

import importlib
import os
import tempfile

import pytest

pytest.importorskip("httpx")

rf = importlib.import_module("gateway.relation_field")
rr = importlib.import_module("gateway.relation_reports")
rp = importlib.import_module("gateway.relation_policy")


def _f():
    return rf.RelationField(tempfile.mkdtemp())


def _rel(**kw):
    base = {"relation_type": rf.DEPENDS_ON, "status": rf.CANDIDATE, "source_classes": ["EXTRACTED_USER_CLAIM"],
            "source_ids": ["s1"], "confidence": 0.6, "origin": "inferred", "subject": "X", "object": "Y",
            "last_reinforced_at": "2025-01-01T00:00:00Z", "last_seen": "2025-01-01T00:00:00Z"}
    base.update(kw)
    return base


# ============================================================ S2 — trust decay
def test_stale_unreinforced_relation_loses_weight():
    r = _rel()
    assert rf.relation_decay(r)["decayed_weight"] < rf.relation_weight_score(r)


def test_canonical_relation_resists_decay():
    r = _rel(status=rf.COMMITTED, origin="canonical_schema", source_classes=["SYSTEM_CANONICAL"])
    d = rf.relation_decay(r)
    assert d["decay_factor"] == 1.0 and d["decayed_weight"] == d["base_weight"]


def test_recently_reinforced_relation_recovers_weight():
    stale = _rel(last_reinforced_at="2025-01-01T00:00:00Z")
    fresh = _rel(last_reinforced_at=rf._now())
    assert rf.relation_decay(fresh)["decayed_weight"] > rf.relation_decay(stale)["decayed_weight"]


def test_disputed_relation_decays_faster():
    cand = _rel(status=rf.CANDIDATE)
    disp = _rel(status=rf.DISPUTED, contradiction_count=1)
    assert rf.relation_decay(disp)["decay_factor"] <= rf.relation_decay(cand)["decay_factor"]


def test_decay_does_not_delete_relation():
    f = _f()
    r = f.ingest_candidate_relation({"subject": "A", "predicate": "depends on", "object": "B",
                                     "relation_type": rf.DEPENDS_ON, "source_id": "s1",
                                     "source_class": "EXTRACTED_USER_CLAIM"})
    r["last_reinforced_at"] = "2025-01-01T00:00:00Z"
    f.decayed_relations()
    assert r["relation_id"] in f._rel               # still present after decay computed


def test_decay_visible_in_status():
    f = _f()
    f.add_relation("A", "depends_on", "B", source_id="s1", source_class="VERIFIED_PROJECT_FACT")
    st = f.status()
    assert "decayed_relations" in st and "stable_relations" in st and st["decay_enabled"] in (True, False)


def test_committed_relation_decays_slower_than_candidate():
    committed = _rel(status=rf.COMMITTED, source_classes=["DOMAIN_VERIFIED"])
    candidate = _rel(status=rf.CANDIDATE, source_classes=["DOMAIN_VERIFIED"])
    assert rf.relation_decay(committed)["decay_factor"] > rf.relation_decay(candidate)["decay_factor"]


def test_tombstoned_source_relation_decays_hard():
    normal = _rel(status=rf.COMMITTED, source_classes=["VERIFIED_PROJECT_FACT"], last_reinforced_at=rf._now())
    tomb = _rel(status=rf.COMMITTED, source_classes=["VERIFIED_PROJECT_FACT"], last_reinforced_at=rf._now(),
                tombstoned=True)
    assert rf.relation_decay(tomb)["decay_factor"] < rf.relation_decay(normal)["decay_factor"]


# ============================================================ S1 — general objective answering
def _obj_field():
    f = _f()
    f.add_relation("BYON", "depends_on", "memory-service", relation_type=rf.DEPENDS_ON,
                   source_id="v1", source_class="VERIFIED_PROJECT_FACT", status=rf.COMMITTED)
    return f


def test_objective_answer_uses_relation_context_when_allowed():
    b = rr.relation_context_bundle(_obj_field(), "ce depinde de BYON?")
    assert b["used"] and b["hits"]


def test_objective_relation_context_blocked_when_source_policy_disallows():
    f = _f()
    f.add_relation("BYON", "depends_on", "SecretSauce", relation_type=rf.DEPENDS_ON, source_id="x1",
                   source_class="EXTRACTED_USER_CLAIM", status=rf.REINFORCED)
    b = rr.relation_context_bundle(f, "ce depinde de BYON?")
    assert b.get("blocked_count", 0) >= 1 and all("SecretSauce" not in str(h) for h in b["hits"])


def test_vault_only_relation_not_objective_truth():
    assert rp.context_allowed(rf.DEPENDS_ON, ["EXTRACTED_USER_CLAIM"], subject="BYON") is False


def test_committed_fact_outprioritizes_relation_context():
    # relation context hits are clearly marked 'relation:' (secondary); a committed memory fact is primary
    hits = rr.relation_context_hits(_obj_field(), "ce depinde de BYON?")
    assert hits and all(h["metadata"]["source"].startswith("relation:") for h in hits)


def test_relation_context_has_sources():
    b = rr.relation_context_bundle(_obj_field(), "ce depinde de BYON?")
    assert b["source_classes"] and b["relation_ids"]


def test_secret_query_skips_relation_context():
    b = rr.relation_context_bundle(_obj_field(), "what is my password?", is_secret=True)
    assert b["blocked"] and b["hits"] == [] and not b["used"]


def test_relation_context_does_not_override_canonical():
    # a vault-only objective relation is excluded from context, so it cannot override canonical
    f = _f()
    f.add_relation("BYON", "depends_on", "vault thing", relation_type=rf.DEPENDS_ON, source_id="x",
                   source_class="EXTRACTED_USER_CLAIM", status=rf.REINFORCED)
    b = rr.relation_context_bundle(f, "ce depinde de BYON?")
    assert not b["used"] or all("vault thing" not in str(h) for h in b["hits"])


def test_relation_context_not_used_as_sole_authority_when_disallowed():
    # only candidate relations -> relation_context_for returns nothing committed -> cannot ground
    f = _f()
    f.ingest_candidate_relation({"subject": "BYON", "predicate": "depends on", "object": "Q",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "s1",
                                 "source_class": "VERIFIED_PROJECT_FACT"})
    ctx = rr.relation_context_for(f, "ce depinde de BYON?")
    assert all(b["status"] in (rf.COMMITTED, rf.REINFORCED) for b in ctx["relations"])


# ============================================================ S3 — grounded path explanation
def _canon_path():
    f = _f()
    f.add_relation("A", "depends_on", "B", relation_type=rf.DEPENDS_ON, source_id="c1",
                   source_class="SYSTEM_CANONICAL", status=rf.COMMITTED, origin="canonical_schema",
                   evidence_quote="A depends on B")
    f.add_relation("B", "depends_on", "C", relation_type=rf.DEPENDS_ON, source_id="c2",
                   source_class="SYSTEM_CANONICAL", status=rf.COMMITTED, origin="canonical_schema",
                   evidence_quote="B depends on C")
    return f


def test_path_explanation_includes_each_hop():
    exp = rr.render_path_explanation(_canon_path(), "A", "C")
    assert len(exp["hops"]) == 2


def test_path_explanation_includes_quotes():
    exp = rr.render_path_explanation(_canon_path(), "A", "C")
    assert all(h["evidence_quote"] for h in exp["hops"])


def test_path_explanation_includes_confidence():
    exp = rr.render_path_explanation(_canon_path(), "A", "C")
    assert all(isinstance(h["confidence"], (int, float)) for h in exp["hops"])


def test_path_explanation_includes_decayed_weight():
    exp = rr.render_path_explanation(_canon_path(), "A", "C")
    assert all("decayed_weight" in h for h in exp["hops"])


def test_disputed_hop_marks_answer_disputed():
    f = _canon_path()
    f.ingest_candidate_relation({"subject": "B", "predicate": "does not depend on", "object": "C",
                                 "relation_type": rf.CONTRADICTS, "is_contradiction": True,
                                 "source_id": "d1", "source_class": "EXTRACTED_USER_CLAIM"})
    assert rr.render_path_explanation(f, "A", "C")["epistemic_status"] == "DISPUTED"


def test_candidate_hop_marks_answer_provisional():
    f = _f()
    f.ingest_candidate_relation({"subject": "A", "predicate": "depends on", "object": "B",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "s1",
                                 "source_class": "VERIFIED_PROJECT_FACT", "evidence_quote": "q"})
    assert rr.render_path_explanation(f, "A", "B")["epistemic_status"] == "PROVISIONAL"


def test_inverse_hop_warning_visible():
    f = _f()
    f.add_relation("A", "broader_than", "B", relation_type=rf.BROADER_THAN, source_id="c1",
                   source_class="SYSTEM_CANONICAL", status=rf.COMMITTED, origin="canonical_schema",
                   evidence_quote="A broader than B")
    exp = rr.render_path_explanation(f, "B", "A", include_inverse=True)
    assert exp["inverse_rendered"] and "invers" in exp["answer"].lower()


def test_canonical_path_answer_known():
    assert rr.render_path_explanation(_canon_path(), "A", "C")["epistemic_status"] == "KNOWN"


def test_path_explanation_rejects_unsourced_hop():
    f = _f()
    f.add_relation("A", "depends_on", "B", relation_type=rf.DEPENDS_ON, source_id=None,
                   source_class="SYSTEM_CANONICAL", status=rf.COMMITTED, origin="canonical_schema")
    assert rr.render_path_explanation(f, "A", "B")["epistemic_status"] != "KNOWN"


# ============================================================ S4 — contradiction evolution
def _disputed():
    f = _f()
    f.add_relation("P", "depends_on", "Q", relation_type=rf.DEPENDS_ON, source_id="s1",
                   source_class="DOMAIN_VERIFIED")
    f.ingest_candidate_relation({"subject": "P", "predicate": "does not depend on", "object": "Q",
                                 "relation_type": rf.CONTRADICTS, "is_contradiction": True,
                                 "source_id": "s2", "source_class": "EXTRACTED_USER_CLAIM"})
    return f


def test_contradiction_history_recorded():
    assert _disputed().contradiction_history()


def test_resolved_temporal_conflict_downgrades_pressure():
    f = _disputed()
    cid = f.contradiction_history()[0]["contradiction_id"]
    f.resolve_contradiction(cid, resolution_source="operator")
    unresolved = [c for c in f.contradiction_history() if c["current_status"] not in ("resolved", "superseded")]
    assert all(c["contradiction_id"] != cid for c in unresolved)


def test_canonical_conflict_stays_active_until_archived_or_overridden():
    f = _f()
    f.ingest_candidate_relation({"subject": "BYON", "predicate": "is", "object": "level 3",
                                 "relation_type": rf.CONTRADICTS, "is_contradiction": True,
                                 "source_id": "s1", "source_class": "EXTRACTED_USER_CLAIM"})
    h = f.contradiction_history()[0]
    assert h["conflict_type"] == "canonical_conflict" and h["current_status"] == "canonical_overrides"


def test_contradiction_next_action_visible():
    assert _disputed().contradiction_history()[0]["recommended_next_action"]


def test_older_vault_conflict_does_not_override_current_canonical():
    f = _f()
    canon = f.add_relation("BYON", "operational_level", "Level 2", relation_type=rf.ROLE_OF,
                           source_id="c1", source_class="SYSTEM_CANONICAL", status=rf.COMMITTED,
                           origin="canonical_schema")
    vault = _rel(status=rf.DISPUTED, source_classes=["EXTRACTED_USER_CLAIM"])
    assert rf.relation_decay(canon)["decayed_weight"] > rf.relation_decay(vault)["decayed_weight"]


def test_source_scope_conflict_classified():
    f = _f()
    r = f.add_relation("G", "depends_on", "D", relation_type=rf.DEPENDS_ON, source_id="s1",
                       source_class="EXTRACTED_USER_CLAIM", is_contradiction=True)
    r["source_classes"] = ["EXTRACTED_USER_CLAIM", "VERIFIED_PROJECT_FACT"]
    assert f.classify_conflict(r) == "source_scope_conflict"


def test_direct_contradiction_classified():
    f = _disputed()
    dep = next(r for r in f._rel.values() if r["relation_type"] == rf.DEPENDS_ON)
    assert f.classify_conflict(dep) in ("direct_contradiction", "source_scope_conflict", "temporal_conflict")


def test_contradiction_resolution_source_recorded():
    f = _disputed()
    cid = f.contradiction_history()[0]["contradiction_id"]
    rec = f.resolve_contradiction(cid, resolution_source="verified:doc")
    assert rec["resolution_source"] == "verified:doc"


# ============================================================ S5 — relation-gap tasks
class FakeTasks:
    def __init__(self):
        self.created = []

    def create(self, *, topic, question, trigger_event_ids=None, priority=1.0, allowed_sources=None,
               is_secret=False):
        if is_secret:
            return None
        t = {"task_id": "rt_" + str(len(self.created)), "topic": topic, "allowed_sources":
             allowed_sources or ["memory", "vault", "self_state"], "question": question}
        self.created.append(t)
        return t


def test_weak_relation_gap_creates_research_task():
    f = _f()
    f.ingest_candidate_relation({"subject": "Weak", "predicate": "depends on", "object": "Thing",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "w1",
                                 "source_class": "EXTRACTED_USER_CLAIM"})
    tq = FakeTasks()
    gaps = rf.RelationGapScanner(f, tasks=tq).scan()
    assert gaps and tq.created


def test_disputed_relation_creates_resolution_task():
    tq = FakeTasks()
    gaps = rf.RelationGapScanner(_disputed(), tasks=tq).scan()
    assert any(g["gap_type"] == "resolve_dispute" for g in gaps)


def test_vault_only_objective_relation_requests_verified_source():
    f = _f()
    f.add_relation("Vobj", "depends_on", "Other", relation_type=rf.DEPENDS_ON, source_id="v1",
                   source_class="EXTRACTED_USER_CLAIM", status=rf.REINFORCED)
    gaps = rf.RelationGapScanner(f, tasks=FakeTasks()).scan()
    assert any(g["gap_type"] == "verify_with_project_source" for g in gaps)


def test_web_required_task_blocked_for_permission():
    f = _f()
    f.add_relation("W", "depends_on", "Z", relation_type=rf.DEPENDS_ON, source_id="w1",
                   source_class="PROVISIONAL_WEB")
    gaps = rf.RelationGapScanner(f, tasks=FakeTasks()).scan()
    web = [g for g in gaps if g["gap_type"] == "request_web_permission"]
    assert web and "web" in web[0]["allowed_sources"]


def test_task_result_candidate_only():
    # memory-only gap tasks are auto-runnable; their results become candidates via the existing runner
    f = _f()
    f.ingest_candidate_relation({"subject": "Weak", "predicate": "depends on", "object": "Thing",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "w1",
                                 "source_class": "EXTRACTED_USER_CLAIM"})
    gaps = rf.RelationGapScanner(f, tasks=FakeTasks()).scan()
    assert all("web" not in g["allowed_sources"] for g in gaps if g["gap_type"] == "find_internal_evidence")


def test_central_weak_node_creates_review_task():
    f = _f()
    # a central node (degree>=2) with stale candidate edges
    for i, obj in enumerate(["E1", "E2", "E3"]):
        r = f.ingest_candidate_relation({"subject": "Hub", "predicate": "depends on", "object": obj,
                                         "relation_type": rf.DEPENDS_ON, "source_id": f"s{i}",
                                         "source_class": "EXTRACTED_USER_CLAIM"})
        r["last_reinforced_at"] = "2025-01-01T00:00:00Z"
        f._rel[r["relation_id"]] = r
    gaps = rf.RelationGapScanner(f, tasks=FakeTasks()).scan()
    assert gaps                                          # weak hub produced at least one gap task


def test_failed_path_creates_missing_relation_task():
    f = _f()
    gap = rf.RelationGapScanner(f, tasks=FakeTasks()).scan_path_gap("Nowhere", "Elsewhere")
    assert gap and gap["gap_type"] == "inspect_relation_gap"


def test_secret_relation_gap_no_task():
    f = _f()
    f.ingest_candidate_relation({"subject": "my password", "predicate": "depends on", "object": "vault",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "s1",
                                 "source_class": "EXTRACTED_USER_CLAIM"})
    gaps = rf.RelationGapScanner(f, tasks=FakeTasks()).scan()
    assert all(g.get("skipped") == "secret" or g.get("task_id") for g in gaps)
    assert any(g.get("skipped") == "secret" for g in gaps)


# ============================================================ S6 — relation-aware self-state
def _metric_field():
    f = _f()
    f.add_relation("BYON", "has_component", "D_Cortex", relation_type=rf.HAS_COMPONENT, source_id="c1",
                   source_class="SYSTEM_CANONICAL", status=rf.COMMITTED, origin="canonical_schema")
    old = f.ingest_candidate_relation({"subject": "Foo", "predicate": "depends on", "object": "Bar",
                                       "relation_type": rf.DEPENDS_ON, "source_id": "s1",
                                       "source_class": "EXTRACTED_USER_CLAIM"})
    old["last_reinforced_at"] = "2025-01-01T00:00:00Z"
    f._rel[old["relation_id"]] = old
    return f


def test_decayed_relations_report():
    assert rr.decayed_relations_report(_metric_field())["decayed_relations"]


def test_stable_relations_report():
    assert rr.stable_relations_report(_metric_field())["stable_relations"]


def test_weak_central_nodes_report():
    f = _metric_field()
    f.ingest_candidate_relation({"subject": "Foo", "predicate": "depends on", "object": "Baz",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "s2",
                                 "source_class": "EXTRACTED_USER_CLAIM"})
    assert isinstance(rr.weak_central_nodes_report(f)["weak_central_nodes"], list)


def test_unresolved_contradictions_report():
    assert rr.unresolved_contradictions_report(_disputed())["unresolved_contradictions"]


def test_relation_self_state_uses_decay_metrics():
    st = _metric_field().status()
    assert {"decayed_relations", "stable_relations", "weak_central_nodes", "active_contradictions"} <= set(st)


def test_recently_reinforced_relations_report():
    f = _f()
    f.add_relation("P", "depends_on", "Q", source_id="s1", source_class="VERIFIED_PROJECT_FACT")
    f.add_relation("P", "depends_on", "Q", source_id="s2", source_class="VERIFIED_PROJECT_FACT")
    assert f.recently_reinforced()


def test_relation_gaps_visible_in_self_state():
    st = _metric_field().status()
    assert "weak_central_nodes" in st and "decayed_relations" in st


# ============================================================ S7 — answer safety metadata
def test_relation_context_metadata_present():
    b = rr.relation_context_bundle(_obj_field(), "ce depinde de BYON?")
    assert {"used", "source_classes", "relation_ids", "any_disputed", "any_candidate", "any_decayed"} <= set(b)


def test_relation_context_cannot_override_system_canonical():
    # vault-only objective relations are excluded from context, so they can't override canonical
    assert rp.context_allowed(rf.HAS_COMPONENT, ["EXTRACTED_USER_CLAIM"], subject="BYON") is False


def test_relation_context_cannot_turn_unknown_known_without_source():
    # only committed/reinforced relations are offered as context; candidate-only is never grounding
    f = _f()
    f.ingest_candidate_relation({"subject": "BYON", "predicate": "depends on", "object": "Q",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "s1",
                                 "source_class": "VERIFIED_PROJECT_FACT"})
    assert rr.relation_context_for(f, "ce depinde de BYON?")["relations"] == []


def test_candidate_path_not_known():
    f = _f()
    f.ingest_candidate_relation({"subject": "A", "predicate": "depends on", "object": "B",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "s1",
                                 "source_class": "VERIFIED_PROJECT_FACT", "evidence_quote": "q"})
    assert rr.render_path_explanation(f, "A", "B")["epistemic_status"] != "KNOWN"


def test_inverse_rendered_path_not_stored_truth():
    f = _f()
    f.add_relation("A", "broader_than", "B", relation_type=rf.BROADER_THAN, source_id="c1",
                   source_class="SYSTEM_CANONICAL", status=rf.COMMITTED, origin="canonical_schema")
    exp = rr.render_path_explanation(f, "B", "A", include_inverse=True)
    assert exp["epistemic_status"] != "KNOWN"
    assert not any(r["relation_type"] == rf.NARROWER_THAN for r in f._rel.values())


def test_vault_only_objective_relation_answer_provisional():
    f = _f()
    f.add_relation("V", "depends_on", "W", relation_type=rf.DEPENDS_ON, source_id="v1",
                   source_class="EXTRACTED_USER_CLAIM", status=rf.REINFORCED, evidence_quote="q")
    # such a vault-only objective relation cannot yield a KNOWN path
    assert rr.render_path_explanation(f, "V", "W")["epistemic_status"] != "KNOWN"
