"""Cycle 10 - relational memory field v1.

S1 model + store, S2 ingestion from existing memory, S3 relation-aware retrieval, S4 reports +
intent, S5 temporal tracking, S6 API/UI. The field navigates structure over the memory BYON
already has; it is never a truth authority and never overrides source policy.
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect

import pytest

pytest.importorskip("httpx")

rf = importlib.import_module("gateway.relation_field")
rr = importlib.import_module("gateway.relation_reports")
qr = importlib.import_module("gateway.query_router")
sp = importlib.import_module("gateway.source_policy")


def _field(tmp_path):
    return rf.RelationField(tmp_path)


# ---------------- fakes for ingestion ----------------
class FakeLC:
    def __init__(self, candidates=None, disputes=None):
        self._c = candidates or []
        self._d = disputes or []

    def list(self, status=None):
        return self._c

    def list_disputes(self):
        return self._d

    def get(self, cid):
        return next((c for c in self._c if c.get("candidate_id") == cid), None)


class FakeVM:
    def __init__(self, files):
        self._by_chunk = {f"obsidian:{p}#chunk:0:aa": {"file_path": p, "chunk_id": f"obsidian:{p}#chunk:0:aa",
                                                        "status": "active"} for p in files}


def _cand(**kw):
    base = {"candidate_id": "cand_x", "topic": "topic alpha", "claim": "topic alpha is real",
            "status": "candidate", "source_class": "EXTRACTED_USER_CLAIM", "challenger_of": None,
            "semantic_relation": None}
    base.update(kw)
    return base


# ============================================================ S1 - model
def test_entity_created_from_committed_fact(tmp_path):
    f = _field(tmp_path)
    f.add_relation("BYON", "has_component", "D_Cortex", source_class="VERIFIED_PROJECT_FACT",
                   source_id="relation:BYON->has_component->D_Cortex", status=rf.COMMITTED)
    assert f.get_entity("BYON") is not None and f.get_entity("D_Cortex") is not None


def test_entity_aliases_merged(tmp_path):
    f = _field(tmp_path)
    f.add_entity("D_Cortex")
    f.register_alias("D_Cortex", "D-Cortex")
    assert f.resolve("D-Cortex") == f.resolve("D_Cortex")
    assert f.get_entity("D-Cortex")["canonical_name"] == "D_Cortex"


def test_relation_created_from_candidate(tmp_path):
    f = _field(tmp_path)
    b = rf.RelationFieldBuilder(f, lifecycle=FakeLC([_cand(status="committed")]))
    b.ingest_candidate(_cand(status="committed"))
    rels = f.relations_for("topic alpha")
    assert any(r["relation_type"] == rf.CONSOLIDATION_PROMOTED for r in rels)


def test_contradiction_relation_marked_disputed(tmp_path):
    f = _field(tmp_path)
    r = f.add_relation("X", "contradicts", "Y", source_class="EXTRACTED_USER_CLAIM",
                       is_contradiction=True)
    assert r["status"] == rf.DISPUTED and r["contradiction_count"] >= 1


def test_canonical_relation_outprioritizes_vault_relation(tmp_path):
    f = _field(tmp_path)
    f.add_relation("Topic", "mentioned_in", "vault", source_class="EXTRACTED_USER_CLAIM",
                   source_id="vault:n#chunk")
    f.add_relation("BYON", "has_component", "Topic", source_class="VERIFIED_PROJECT_FACT",
                   source_id="relation:BYON->has_component->Topic", status=rf.COMMITTED)
    top = f.relations_for("Topic")[0]
    assert "VERIFIED_PROJECT_FACT" in top["source_classes"] and top["status"] == rf.COMMITTED


def test_relation_field_not_truth_authority(tmp_path):
    f = _field(tmp_path)
    assert rf.IS_TRUTH_AUTHORITY is False
    assert f.status()["is_truth_authority"] is False and f.status()["answers_user_directly"] is False


# ============================================================ S2 - ingestion
def test_rebuild_from_candidates(tmp_path):
    f = _field(tmp_path)
    lc = FakeLC([_cand(candidate_id="c1", topic="memory consistency", status="committed",
                       source_class="DOMAIN_VERIFIED")])
    rf.RelationFieldBuilder(f, lifecycle=lc).rebuild()
    assert f.get_entity("memory consistency") is not None
    assert any(r["relation_type"] == rf.CONSOLIDATION_PROMOTED for r in f.relations_for("memory consistency"))


def test_rebuild_from_disputes(tmp_path):
    f = _field(tmp_path)
    disp = [{"candidate_id": "c1", "challenger_id": "c2", "relation": "contradicts",
             "evidence_a": "server is up", "evidence_b": "server is down",
             "source_class_a": "EXTRACTED_USER_CLAIM", "ts": "2026-05-01T00:00:00Z"}]
    rf.RelationFieldBuilder(f, lifecycle=FakeLC(disputes=disp)).rebuild()
    assert len(f.contradictions()) >= 1


def test_rebuild_from_vault_sources(tmp_path):
    f = _field(tmp_path)
    vm = FakeVM(["notes/FCE-M design.md", "notes/byon arch.md"])
    rf.RelationFieldBuilder(f, lifecycle=FakeLC(), vault_manifest=vm, lifeloop_dir=tmp_path).rebuild()
    assert any(r["relation_type"] == rf.MENTIONED_IN for r in f._rel.values())


def test_incremental_update_from_event(tmp_path):
    f = _field(tmp_path)
    b = rf.RelationFieldBuilder(f, lifeloop_dir=tmp_path)
    out = b.incremental_update({"type": "relation", "subject": "A", "predicate": "depends_on",
                                "object": "B", "source_class": "VERIFIED_PROJECT_FACT"})
    assert out["new_relation"] and f.get_entity("A") is not None


def test_duplicate_relation_not_recreated(tmp_path):
    f = _field(tmp_path)
    f.add_relation("A", "depends_on", "B", source_id="s1", source_class="VERIFIED_PROJECT_FACT")
    n1 = f.counts()["relations"]
    f.add_relation("A", "depends_on", "B", source_id="s1", source_class="VERIFIED_PROJECT_FACT")
    assert f.counts()["relations"] == n1 == 1


# ============================================================ S3 - relation-aware retrieval
def _built(tmp_path):
    f = _field(tmp_path)
    rf.RelationFieldBuilder(f, lifeloop_dir=tmp_path).rebuild()
    f.add_relation("FCE-M", "contradicts", "FCE-M can approve actions",
                   source_class="EXTRACTED_USER_CLAIM", is_contradiction=True)
    return f


def test_relation_query_uses_relation_field(tmp_path):
    out = rr.render_answer(_built(tmp_path), "ce concepte sunt legate de BYON?")
    assert out["status"] == "KNOWN" and "D_Cortex" in out["answer"]


def test_dependency_query_returns_depends_on(tmp_path):
    out = rr.render_answer(_built(tmp_path), "ce depinde de BYON?")
    assert out["kind"] == "dependency_map" and "has_component" in out["answer"]


def test_contradiction_query_returns_disputed_relations(tmp_path):
    out = rr.render_answer(_built(tmp_path), "ce contradictii exista in jurul FCE-M?")
    assert out["kind"] == "contradiction_map"


def test_concept_neighborhood_query_returns_related_entities(tmp_path):
    nb = _built(tmp_path).neighborhood("BYON")
    assert "D_Cortex" in nb["related_entities"]


def test_relation_answer_has_sources(tmp_path):
    out = rr.render_answer(_built(tmp_path), "ce concepte sunt legate de BYON?")
    assert out["sources"] and "relation:field" in out["sources"]


def test_relation_answer_passes_source_policy(tmp_path):
    out = rr.render_answer(_built(tmp_path), "ce concepte sunt legate de BYON?")
    assert out["source_class"] in sp.ALLOWED_PRIMARY[sp.Q_OPERATIONAL]


# ============================================================ S4 - reports + intent
def test_relation_field_query_detected():
    assert qr.classify_intent("care este relatia dintre BYON si D_Cortex?") == qr.RELATION_FIELD_QUERY
    assert qr.classify_intent("ce depinde de BYON?") == qr.RELATION_FIELD_QUERY
    assert qr.classify_intent("Cine este BYON?") != qr.RELATION_FIELD_QUERY


def test_entity_neighborhood_report(tmp_path):
    rep = rr.entity_neighborhood(_built(tmp_path), "BYON")
    assert rep["found"] and rep["relations"]


def test_contradiction_map_report(tmp_path):
    rep = rr.contradiction_map(_built(tmp_path))
    assert rep["count"] >= 1


def test_recurrent_themes_report(tmp_path):
    rep = rr.recurrent_themes(_built(tmp_path))
    assert rep["themes"]


def test_source_breakdown_report(tmp_path):
    rep = rr.source_breakdown(_built(tmp_path))
    assert "VERIFIED_PROJECT_FACT" in rep["by_source_class"]


# ============================================================ S5 - temporal tracking
def test_relation_temporal_history_written(tmp_path):
    f = _field(tmp_path)
    r = f.add_relation("A", "depends_on", "B", source_id="s1", source_class="VERIFIED_PROJECT_FACT")
    assert r["source_history"] and r["first_seen"] and r["last_seen"]


def test_recent_relation_changes_query(tmp_path):
    rep = rr.recent_relation_changes(_built(tmp_path))
    assert rep["changes"]


def test_relation_reinforcement_updates_last_seen(tmp_path):
    f = _field(tmp_path)
    f.add_relation("A", "depends_on", "B", source_id="s1", source_class="VERIFIED_PROJECT_FACT",
                   ts="2026-01-01T00:00:00Z")
    r = f.add_relation("A", "depends_on", "B", source_id="s2", source_class="VERIFIED_PROJECT_FACT",
                       ts="2026-02-01T00:00:00Z")
    assert r["reinforcement_count"] >= 1 and r["last_seen"] == "2026-02-01T00:00:00Z"
    assert r["evidence_count"] == 2


def test_disputed_relation_records_contradicted_at(tmp_path):
    f = _field(tmp_path)
    r = f.add_relation("X", "contradicts", "Y", source_class="EXTRACTED_USER_CLAIM",
                       is_contradiction=True, ts="2026-03-03T00:00:00Z")
    assert r["contradicted_at"] == "2026-03-03T00:00:00Z"


# ============================================================ S6 - API / UI
@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from fastapi.testclient import TestClient
    from gateway.app import create_app
    from gateway.config import GatewayConfig
    from gateway.alpha_validation import StubBYONBackend
    work = tmp_path_factory.mktemp("rf_app")
    cfg = dataclasses.replace(GatewayConfig.from_env(), users_root=str(work / "users"),
                              audit_root=str(work / "audit"))
    app = create_app(cfg, backend=StubBYONBackend())
    return TestClient(app)


def test_relation_status_endpoint(client):
    r = client.get("/v1/lifeloop/relation-field/status").json()
    assert r["is_truth_authority"] is False and r["total_relations"] >= 1


def test_relation_entity_endpoint(client):
    client.post("/v1/lifeloop/relation-field/rebuild")
    r = client.get("/v1/lifeloop/relation-field/entity/BYON")
    assert r.status_code == 200 and r.json()["entity"]["canonical_name"] == "BYON"


def test_relation_neighborhood_endpoint(client):
    client.post("/v1/lifeloop/relation-field/rebuild")
    r = client.get("/v1/lifeloop/relation-field/neighborhood/BYON").json()
    rels = r["neighborhood"]["relations"]
    assert any(x["relation_type"] == "has_component" for x in rels)


def test_relation_contradictions_endpoint(client):
    r = client.get("/v1/lifeloop/relation-field/contradictions").json()
    assert isinstance(r["count"], int) and r["is_truth_authority"] is False


def test_ui_calls_gateway_only():
    src = inspect.getsource(importlib.import_module("app.alpha_ui"))
    # the relation panel handlers must go through the gateway client only
    assert "client.relation_field_status" in src and "client.relation_field_rebuild" in src
    assert "client.relation_field_neighborhood" in src and "client.relation_field_contradictions" in src
    # the UI never talks to memory-service / the network directly - only via the gateway client
    assert "import httpx" not in src and "import requests" not in src
    assert "/v1/lifeloop/relation-field" not in src    # no hand-rolled gateway paths in the UI
