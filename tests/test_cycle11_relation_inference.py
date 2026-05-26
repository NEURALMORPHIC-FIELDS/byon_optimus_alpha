"""Cycle 11 — grounded relation inference + relational reasoning.

S1 extractor, S2 content ingestion, S3 multi-hop, S4 relation-candidate lifecycle, S5 proposals,
S6 rendering. Inference produces CANDIDATES with provenance, never truth; Claude is advisory-only;
secrets are never inferred from; source policy + the Auditor remain dominant.
"""
from __future__ import annotations

import importlib
import os
import time

import pytest

pytest.importorskip("httpx")

ri = importlib.import_module("gateway.relation_inference")
rf = importlib.import_module("gateway.relation_field")
rr = importlib.import_module("gateway.relation_reports")


def _field(tmp_path):
    return rf.RelationField(tmp_path)


class FakeMem:
    """Returns canned hits per (thread_id, query) so inference reads CONTENT, not filenames."""
    def __init__(self, system=None, by_owner=None):
        self.system = system or []
        self.by_owner = by_owner or {}

    def search_facts(self, query, *, top_k=25, threshold=0.0, thread_id=None, scope="thread"):
        return list(self.system if thread_id is None else self.by_owner.get(thread_id, []))


def _hit(content, source, trust):
    return {"content": content, "ctx_id": abs(hash(source)) % 9999,
            "metadata": {"source": source, "trust": trust}}


class FakeLC:
    def __init__(self):
        self.calls = []

    def ingest_task_result(self, **kw):
        self.calls.append(kw)
        return {"candidate_id": "cand_" + str(len(self.calls)), "status": "candidate", **kw}

    def get(self, cid):
        return None


# ============================================================ S1 — extractor
def test_deterministic_relation_extracted_from_committed_fact():
    cs = ri.infer_relations_from_text("BYON gateway depends on memory-service.",
                                      "committed:f1", "VERIFIED_PROJECT_FACT", {})
    assert any(c["relation_type"] == rf.DEPENDS_ON and "memory-service" in c["object"] for c in cs)
    assert cs[0]["method"] == ri.M_DETERMINISTIC


def test_relation_candidate_has_quote_and_source():
    cs = ri.infer_relations_from_text("The Auditor contains a verifier stage.",
                                      "committed:f2", "VERIFIED_PROJECT_FACT", {"ctx_id": 5})
    c = cs[0]
    assert c["evidence_quote"] and c["source_id"] == "committed:f2" and c["source_class"]


def test_claude_relation_inference_advisory_only():
    os.environ["BYON_RELATION_INFERENCE_CLAUDE"] = "true"
    try:
        advisor = lambda snippet: [{"subject": "X", "predicate": "depends on", "object": "Y"}]
        cs = ri.infer_relations_from_text("some prose with no deterministic pattern here",
                                          "src", "DOMAIN_VERIFIED", {}, claude_advisor=advisor)
        adv = [c for c in cs if c["method"] == ri.M_CLAUDE]
        assert adv and adv[0]["status"] == rf.CANDIDATE and adv[0]["confidence"] <= 0.6
    finally:
        os.environ.pop("BYON_RELATION_INFERENCE_CLAUDE", None)


def test_secret_text_not_sent_to_claude():
    os.environ["BYON_RELATION_INFERENCE_CLAUDE"] = "true"
    seen = []
    try:
        advisor = lambda snippet: seen.append(snippet) or []
        cs = ri.infer_relations_from_text("my password is hunter2 and the api key is abc",
                                          "src", "EXTRACTED_USER_CLAIM", {}, claude_advisor=advisor)
        assert cs == [] and seen == []                  # secret never inferred from, never sent
    finally:
        os.environ.pop("BYON_RELATION_INFERENCE_CLAUDE", None)


def test_vault_relation_kept_user_memory_grounded():
    cs = ri.infer_relations_from_text("Helios depends on the calibration module.",
                                      "vault:notes/h.md#chunk", "EXTRACTED_USER_CLAIM", {})
    assert cs and cs[0]["source_class"] == "EXTRACTED_USER_CLAIM" and cs[0]["status"] == rf.CANDIDATE


def test_canonical_relation_outranks_inferred_vault_relation(tmp_path):
    f = _field(tmp_path)
    f.add_relation("BYON", "has_component", "Topic", source_class="VERIFIED_PROJECT_FACT",
                   source_id="relation:seed", status=rf.COMMITTED, origin="canonical_schema")
    for c in ri.infer_relations_from_text("Topic depends on a personal note.", "vault:n#c",
                                          "EXTRACTED_USER_CLAIM", {}):
        f.ingest_candidate_relation(c)
    top = f.relations_for("Topic")[0]
    assert top["status"] == rf.COMMITTED and "VERIFIED_PROJECT_FACT" in top["source_classes"]


# ============================================================ S2 — content ingestion
def test_relation_inference_uses_fact_content(tmp_path):
    mem = FakeMem(system=[_hit("BYON gateway depends on memory-service", "repo:arch.md", "VERIFIED_PROJECT_FACT")])
    f = _field(tmp_path)
    n = rf.RelationFieldBuilder(f, mem_client=mem).infer_from_memory()
    assert n >= 1 and any(r["relation_type"] == rf.DEPENDS_ON and r.get("evidence_quote")
                          for r in f._rel.values())


def test_vault_relation_from_chunk_content_not_filename_only(tmp_path):
    mem = FakeMem(by_owner={"u": [_hit("Helios depends on the calibration module",
                                       "vault:notes/sys.md#chunk:0", "EXTRACTED_USER_CLAIM")]})
    f = _field(tmp_path)
    rf.RelationFieldBuilder(f, mem_client=mem, owners=["u"]).infer_from_memory()
    rels = [r for r in f._rel.values() if "helios" in r["subject"].lower()]
    assert rels and rels[0]["source_classes"] == ["EXTRACTED_USER_CLAIM"] and rels[0].get("evidence_quote")


def test_self_training_doc_relation_inferred(tmp_path):
    mem = FakeMem(system=[_hit("Claude functions as the language faculty", "repo:README.md", "VERIFIED_PROJECT_FACT")])
    f = _field(tmp_path)
    rf.RelationFieldBuilder(f, mem_client=mem).infer_from_memory()
    assert any(r["relation_type"] == rf.ROLE_OF for r in f._rel.values())


def test_task_result_relation_inferred(tmp_path):
    f = _field(tmp_path)
    rf.RelationFieldBuilder(f).ingest_task_result(
        {"task_id": "t1", "topic": "x", "answer_summary": "D_Cortex depends on FCE-M"})
    assert any(r["relation_type"] == rf.DEPENDS_ON for r in f._rel.values())


# ============================================================ S3 — multi-hop
def _chain(tmp_path, sc="VERIFIED_PROJECT_FACT", extra=None):
    f = _field(tmp_path)
    f.add_relation("A", "depends_on", "B", relation_type=rf.DEPENDS_ON, source_id="s1", source_class=sc)
    f.add_relation("B", "depends_on", "C", relation_type=rf.DEPENDS_ON, source_id="s2", source_class=sc)
    return f


def test_two_hop_path_query(tmp_path):
    res = _chain(tmp_path).multi_hop_path("A", "C", max_depth=2)
    assert res["paths"] and res["paths"][0]["length"] == 2


def test_path_answer_includes_each_hop_source(tmp_path):
    res = _chain(tmp_path).multi_hop_path("A", "C", max_depth=2)
    hops = res["paths"][0]["hops"]
    assert all(h["source_ids"] and h["source_classes"] for h in hops)


def test_disputed_hop_marks_path_disputed(tmp_path):
    f = _chain(tmp_path)
    f.ingest_candidate_relation({"subject": "B", "predicate": "does not depend on", "object": "C",
                                 "relation_type": rf.CONTRADICTS, "is_contradiction": True,
                                 "source_id": "s3", "source_class": "EXTRACTED_USER_CLAIM",
                                 "evidence_quote": "B does not depend on C"})
    res = f.multi_hop_path("A", "C", max_depth=2)
    assert any(p["path_status"] == rf.DISPUTED for p in res["paths"])


def test_max_depth_enforced(tmp_path):
    f = _chain(tmp_path)
    f.add_relation("C", "depends_on", "D", relation_type=rf.DEPENDS_ON, source_id="s4",
                   source_class="VERIFIED_PROJECT_FACT")
    assert _field_path_lengths(f, "A", "D", 2) == []          # 3 hops not allowed at depth 2
    assert _field_path_lengths(f, "A", "C", 2)                # 2 hops allowed


def _field_path_lengths(f, a, b, d):
    return [p["length"] for p in f.multi_hop_path(a, b, max_depth=d)["paths"]]


def test_canonical_path_outprioritizes_vault_path(tmp_path):
    f = _field(tmp_path)
    f.add_relation("A", "has_component", "M", source_id="c1", source_class="SYSTEM_CANONICAL")
    f.add_relation("M", "has_component", "Z", source_id="c2", source_class="SYSTEM_CANONICAL")
    f.add_relation("A", "mentioned_in", "V", source_id="v1", source_class="EXTRACTED_USER_CLAIM")
    f.add_relation("V", "mentioned_in", "Z", source_id="v2", source_class="EXTRACTED_USER_CLAIM")
    res = f.multi_hop_path("A", "Z", max_depth=2)
    assert res["paths"][0]["canonical"] is True


# ============================================================ S4 — relation lifecycle
def _ingest(f, subj, obj, src, sc="VERIFIED_PROJECT_FACT"):
    return f.ingest_candidate_relation({"subject": subj, "predicate": "depends on", "object": obj,
                                        "relation_type": rf.DEPENDS_ON, "source_id": src,
                                        "source_class": sc, "evidence_quote": f"{subj} depends on {obj}"})


def test_inferred_relation_starts_candidate(tmp_path):
    f = _field(tmp_path)
    r = _ingest(f, "P", "Q", "s1")
    assert r["status"] == rf.CANDIDATE


def test_repeated_independent_relation_reinforces(tmp_path):
    f = _field(tmp_path)
    _ingest(f, "P", "Q", "s1")
    r = _ingest(f, "P", "Q", "s2")
    assert r["status"] == rf.REINFORCED and len(set(r["source_ids"])) == 2


def test_relation_commits_after_threshold(tmp_path):
    f = _field(tmp_path)
    _ingest(f, "P", "Q", "s1")
    _ingest(f, "P", "Q", "s2")
    f.consolidate()
    assert f.relations_for("P")[0]["status"] == rf.COMMITTED


def test_contradictory_relation_disputes(tmp_path):
    f = _field(tmp_path)
    _ingest(f, "P", "Q", "s1")
    f.ingest_candidate_relation({"subject": "P", "predicate": "does not depend on", "object": "Q",
                                 "relation_type": rf.CONTRADICTS, "is_contradiction": True,
                                 "source_id": "s2", "source_class": "EXTRACTED_USER_CLAIM"})
    dep = next(r for r in f._rel.values() if r["relation_type"] == rf.DEPENDS_ON)
    assert dep["status"] == rf.DISPUTED and dep["contradicted_at"]


def test_weak_relation_archives(tmp_path):
    f = _field(tmp_path)
    r = _ingest(f, "P", "Q", "s1", sc="EXTRACTED_USER_CLAIM")
    r["first_seen"] = "2025-01-01T00:00:00Z"            # age it beyond the stale window
    f._rel[r["relation_id"]] = r
    f.consolidate(stale_days=30)
    assert f.relations_for("P")[0]["status"] == rf.ARCHIVED


def test_system_canonical_relation_can_commit_directly_if_policy_allows(tmp_path):
    f = _field(tmp_path)
    r = f.add_relation("S", "has_component", "T", source_id="c1", source_class="SYSTEM_CANONICAL")
    assert r["status"] == rf.COMMITTED


# ============================================================ S5 — proposals
def _disputed_field(tmp_path, canonical=False):
    f = _field(tmp_path)
    sc = "SYSTEM_CANONICAL" if canonical else "EXTRACTED_USER_CLAIM"
    origin = "canonical_schema" if canonical else "inferred"
    f.add_relation("P", "depends_on", "Q", source_id="s1", source_class=sc, origin=origin,
                   status=(rf.COMMITTED if canonical else None))
    f.ingest_candidate_relation({"subject": "P", "predicate": "does not depend on", "object": "Q",
                                 "relation_type": rf.CONTRADICTS, "is_contradiction": True,
                                 "source_id": "s2", "source_class": "EXTRACTED_USER_CLAIM"})
    return f


def test_relation_field_proposes_candidate(tmp_path):
    props = rf.RelationProposer(_disputed_field(tmp_path)).run()
    assert any(p["proposal_type"] == rf.PROPOSAL_CONTRADICTION for p in props)


def test_proposal_goes_to_candidate_lifecycle(tmp_path):
    lc = FakeLC()
    rf.RelationProposer(_disputed_field(tmp_path), lifecycle=lc).run()
    assert lc.calls and all("claim" in c for c in lc.calls)


def test_proposal_not_committed_directly(tmp_path):
    lc = FakeLC()
    props = rf.RelationProposer(_disputed_field(tmp_path), lifecycle=lc).run()
    assert all(p["status"] in (rf.CANDIDATE, rf.DISPUTED) for p in props)
    assert all(c.get("epistemic_status") in ("PROVISIONAL", "DISPUTED") for c in lc.calls)


def test_canonical_conflict_proposal_marked_disputed(tmp_path):
    props = rf.RelationProposer(_disputed_field(tmp_path, canonical=True)).run()
    contra = [p for p in props if p["proposal_type"] == rf.PROPOSAL_CONTRADICTION]
    assert contra and contra[0]["status"] == rf.DISPUTED


# ============================================================ S6 — rendering
def _render_field(tmp_path):
    f = _field(tmp_path)
    f.add_relation("BYON", "has_component", "D_Cortex", source_id="relation:seed",
                   source_class="VERIFIED_PROJECT_FACT", status=rf.COMMITTED,
                   origin="canonical_schema", evidence_quote="BYON has component D_Cortex")
    return f


def test_relation_answer_shows_quote(tmp_path):
    out = rr.render_answer(_render_field(tmp_path), "ce concepte sunt legate de BYON?")
    assert "citat" in out["answer"].lower()


def test_relation_answer_shows_status(tmp_path):
    out = rr.render_answer(_render_field(tmp_path), "ce concepte sunt legate de BYON?")
    assert rf.COMMITTED in out["answer"]


def test_relation_answer_shows_source_class(tmp_path):
    out = rr.render_answer(_render_field(tmp_path), "ce concepte sunt legate de BYON?")
    assert "VERIFIED_PROJECT_FACT" in out["answer"]


def test_weak_relation_answer_not_overstated(tmp_path):
    f = _field(tmp_path)
    f.ingest_candidate_relation({"subject": "Gadget", "predicate": "depends on", "object": "Widget",
                                 "relation_type": rf.DEPENDS_ON, "source_id": "s1",
                                 "source_class": "EXTRACTED_USER_CLAIM",
                                 "evidence_quote": "Gadget depends on Widget"})
    out = rr.render_answer(f, "ce concepte sunt legate de Gadget?")
    assert out["status"] != "KNOWN" and "dovezi" in out["answer"].lower()


def test_vault_relation_answer_framed_as_user_memory(tmp_path):
    f = _field(tmp_path)
    # a committed vault relation (so it is rendered) but framed as user memory, not objective truth
    f.add_relation("Helios", "depends_on", "Calib", source_id="v1", source_class="EXTRACTED_USER_CLAIM",
                   status=rf.COMMITTED, evidence_quote="Helios depends on Calib")
    out = rr.render_answer(f, "ce concepte sunt legate de Helios?")
    assert "memoria ta" in out["answer"].lower() and "vault" in out["answer"].lower()
