# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 15 TRACK D - autonomous gap-repair, routed THROUGH the existing 13.3 acquisition phase.

The two load-bearing proofs:
  - gap_repair_routes_through_acquisition_not_parallel_path: a gap question driven via
    MemoryServiceBackend.research carries the `acquisition` record that ONLY EpistemicSearch.run
    produces (real call path, no parallel acquisition).
  - gap_repair_passes_acquisition_context_repo_root: with repo_root threaded through, the
    project_files adapter demonstrably FIRES (a project_file EvidencePacket is returned); without
    repo_root it stays dark.
"""
from __future__ import annotations

from gateway.lifeloop import BYONLifeLoop
from gateway.memory_service_backend import MemoryServiceBackend
from gateway.relation_field import COMMITTED, REINFORCED, RelationField, RelationGapScanner
from gateway.relation_maintenance import build_gap_acquisition_context
from gateway.research_tasks import BLOCKED_NEEDS_PERMISSION, ResearchTaskQueue


class FakeMem:
    read_consistency_mode = "direct"

    def health(self):
        return {"_reachable": True}

    def search_facts(self, q, **kw):
        return []                              # empty memory -> acquisition escalation runs

    def store_fact(self, *a, **k):
        return {"success": True}

    def stats(self):
        return {}

    def fce_consolidate(self):
        return {"fce_status": "consolidated"}


def _scanner(tmp_path):
    f = RelationField(str(tmp_path / "rf"))
    return f, ResearchTaskQueue(path=str(tmp_path / "tasks.jsonl"))


# ---- gap-type mappings -----------------------------------------------------
def test_weak_relation_gap_autoruns_memory_task(tmp_path):
    f, q = _scanner(tmp_path)
    f.add_relation("Alpha", "depends_on", "Beta", source_id="r1", source_class="DOMAIN_VERIFIED")
    gaps = RelationGapScanner(f, tasks=q).scan()
    g = next(x for x in gaps if x["relation_id"].startswith("Alpha".lower()) or x["subject"] == "Alpha")
    assert g["gap_type"] == "find_internal_evidence"
    assert "web" not in g["allowed_sources"] and g["requires_permission"] is False


def test_disputed_relation_gap_creates_resolution_task(tmp_path):
    f, q = _scanner(tmp_path)
    f.add_relation("Gamma", "contradicts", "Delta", source_id="rd",
                   source_class="EXTRACTED_USER_CLAIM", is_contradiction=True)
    gaps = RelationGapScanner(f, tasks=q).scan()
    assert any(g["gap_type"] == "resolve_dispute" for g in gaps)
    assert any(t["topic"].startswith("relgap:") for t in q.list())


def test_vault_only_objective_gap_requests_verified_source(tmp_path):
    f, q = _scanner(tmp_path)
    f.add_relation("Proj", "depends_on", "Lib", source_id="rv", source_class="EXTRACTED_USER_CLAIM")
    gaps = RelationGapScanner(f, tasks=q).scan()
    assert any(g["gap_type"] == "verify_with_project_source" for g in gaps)


def test_missing_middle_hop_creates_bridge_task(tmp_path):
    f, q = _scanner(tmp_path)
    f.add_relation("Left", "depends_on", "Mid1", source_id="b1", source_class="DOMAIN_VERIFIED")
    f.add_relation("Right", "depends_on", "Mid2", source_id="b2", source_class="DOMAIN_VERIFIED")
    gap = RelationGapScanner(f, tasks=q).scan_bridge_gap("Left", "Right")
    assert gap is not None and gap["gap_type"] == "find_bridge_relation"


def test_high_usage_low_confidence_creates_reinforce_task(tmp_path):
    f, q = _scanner(tmp_path)
    # make "Hub" central + weak via several candidate relations
    for i in range(3):
        f.add_relation("Hub", "depends_on", f"Leaf{i}", source_id=f"h{i}",
                       source_class="EXTRACTED_USER_CLAIM")
    r = f.add_relation("Hub", "role_of", "System", source_id="rc",
                       source_class="DOMAIN_VERIFIED", status=COMMITTED)
    f._rel[r["relation_id"]]["confidence"] = 0.3        # high-usage (central) but low-confidence
    f._rel[r["relation_id"]]["status"] = REINFORCED
    gaps = RelationGapScanner(f, tasks=q).scan()
    assert any(g["gap_type"] == "reinforce_relation" for g in gaps)


def test_secret_gap_no_task(tmp_path):
    f, q = _scanner(tmp_path)
    f.add_relation("my account", "depends_on", "bank password", source_id="rs",
                   source_class="EXTRACTED_USER_CLAIM")
    gaps = RelationGapScanner(f, tasks=q).scan()
    secret_gaps = [g for g in gaps if "password" in (g.get("object", "") + g.get("subject", ""))]
    assert all(g.get("skipped") == "secret" or g.get("task_id") is None for g in secret_gaps)
    assert not any("password" in (t.get("question", "")) for t in q.list())


# ---- autorun / failure / candidate-only ------------------------------------
def _lifeloop(tmp_path, field, runner):
    ll = BYONLifeLoop(events_path=str(tmp_path / "ll" / "e.jsonl"), runtime_dir=str(tmp_path / "ll"))
    ll.maintenance_every_ticks = 1
    ll.gap_scan_every_ticks = 1
    ll.set_relation_field_provider(lambda: field)
    ll.set_task_runner(runner)
    return ll


def test_repeated_failed_gap_task_stops_loop(tmp_path):
    f = RelationField(str(tmp_path / "rf"))
    f.add_relation("Alpha", "depends_on", "Beta", source_id="r1", source_class="DOMAIN_VERIFIED")
    ll = _lifeloop(tmp_path, f, lambda task: {"epistemic_status": "ERROR", "error": "no evidence"})
    blocked = False
    for _ in range(5):
        ll.tick(mem_client=None)
        if any(t["status"] == BLOCKED_NEEDS_PERMISSION for t in ll.tasks.list()
               if t["topic"].startswith("relgap:")):
            blocked = True
            break
    assert blocked, "repeated failure must stop the loop (task blocked for user input)"


def test_task_result_candidate_only(tmp_path):
    f = RelationField(str(tmp_path / "rf"))
    f.add_relation("Alpha", "depends_on", "Beta", source_id="r1", source_class="DOMAIN_VERIFIED")
    ll = _lifeloop(tmp_path, f, lambda task: {"epistemic_status": "PROVISIONAL",
                                              "answer_summary": "found", "stored_as": "candidate"})
    ll.tick(mem_client=None)
    assert ll.last_task_result is not None
    assert ll.last_task_result["stored_as"] in ("candidate", "disputed")  # never committed


# ---- the two PROOFs --------------------------------------------------------
def _project_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "ARCHITECTURE.md").write_text(
        "# Architecture\n\nBYON architecture overview: BYON is the orchestrator and epistemic "
        "auditor; D_Cortex is the additive memory.\n", encoding="utf-8")
    return str(root)


def test_gap_repair_routes_through_acquisition_not_parallel_path(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    backend = MemoryServiceBackend(mem_client=FakeMem())
    out = backend.research(user_id="lifeloop", session_id="t",
                           question="what is BYON architecture overview?",
                           namespace_dir=tmp_path, action="start",
                           acquisition_context={"repo_root": _project_repo(tmp_path)})
    # `acquisition` is produced ONLY by EpistemicSearch.run; its presence proves the real path
    assert "acquisition" in out
    assert out["acquisition"]["ran"] is True
    assert out["acquisition"]["tiers_run"]


def test_gap_repair_passes_acquisition_context_repo_root(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    repo = _project_repo(tmp_path)
    backend = MemoryServiceBackend(mem_client=FakeMem())
    q = "what is BYON architecture overview?"

    with_root = backend.research(user_id="lifeloop", session_id="t", question=q,
                                 namespace_dir=tmp_path, action="start",
                                 acquisition_context={"repo_root": repo})
    types = {p["source"]["type"] for p in with_root["acquisition"]["packets"]}
    assert "project_file" in types, "project_files adapter must fire when repo_root is threaded"

    without_root = backend.research(user_id="lifeloop", session_id="t2", question=q,
                                    namespace_dir=tmp_path, action="start",
                                    acquisition_context={"repo_root": ""})
    types2 = {p["source"]["type"] for p in without_root["acquisition"]["packets"]}
    assert "project_file" not in types2              # the confirmed asterisk: dark without repo_root

    monkeypatch.setenv("BYON_REPO_ROOT", repo)
    assert build_gap_acquisition_context()["repo_root"] == repo
