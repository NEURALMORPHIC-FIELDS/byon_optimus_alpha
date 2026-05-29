# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 15 TRACK C - LifeLoop integration: scheduled maintenance + gap scan + bounded autorun."""
from __future__ import annotations

from gateway.lifeloop import BYONLifeLoop
from gateway.relation_field import RelationField
from gateway.research_tasks import BLOCKED_NEEDS_PERMISSION


def _field_with_gaps(tmp_path, *, extra_candidates=0):
    f = RelationField(str(tmp_path / "rf"))
    # candidate, low-evidence objective relation -> find_internal_evidence (memory-only) gap
    f.add_relation("ConceptA", "depends_on", "ConceptB", source_id="r:cand",
                   source_class="EXTRACTED_USER_CLAIM")
    # provisional-web relation, ev<2 -> request_web_permission (web) gap -> blocked
    f.add_relation("ConceptC", "depends_on", "ConceptD", source_id="r:web",
                   source_class="PROVISIONAL_WEB")
    for i in range(extra_candidates):
        f.add_relation(f"Extra{i}", "depends_on", f"Target{i}", source_id=f"r:e{i}",
                       source_class="EXTRACTED_USER_CLAIM")
    return f


def _lifeloop(tmp_path, field, *, runner=None):
    ll = BYONLifeLoop(events_path=str(tmp_path / "ll" / "events.jsonl"), runtime_dir=str(tmp_path / "ll"))
    ll.maintenance_every_ticks = 1
    ll.gap_scan_every_ticks = 1
    ll.set_relation_field_provider(lambda: field)
    if runner is not None:
        ll.set_task_runner(runner)
    return ll


def _ok_runner(task):
    return {"epistemic_status": "PROVISIONAL", "answer_summary": "internal evidence found",
            "sources_used": ["memory"], "confidence": 0.6, "stored_as": "candidate"}


def test_lifeloop_tick_runs_relation_maintenance(tmp_path):
    ll = _lifeloop(tmp_path, _field_with_gaps(tmp_path))
    out = ll.tick(mem_client=None)
    assert out["relation_maintenance"] is not None
    assert ll.last_relation_maintenance["relations_scanned"] >= 2


def test_lifeloop_tick_scans_relation_gaps(tmp_path):
    ll = _lifeloop(tmp_path, _field_with_gaps(tmp_path))
    out = ll.tick(mem_client=None)
    assert out["relation_gaps"] >= 1
    assert ll.last_gap_scan["gaps_found"] >= 1


def test_lifeloop_creates_tasks_from_gaps(tmp_path):
    ll = _lifeloop(tmp_path, _field_with_gaps(tmp_path))
    ll.tick(mem_client=None)
    assert len(ll.tasks.list()) >= 1


def test_lifeloop_autoruns_memory_only_gap_tasks(tmp_path):
    ll = _lifeloop(tmp_path, _field_with_gaps(tmp_path), runner=_ok_runner)
    out = ll.tick(mem_client=None)
    assert out["tasks_run"]                                   # at least one memory gap task ran
    assert ll.last_auto_run_task is not None


def test_lifeloop_does_not_run_web_gap_task_without_permission(tmp_path):
    field = _field_with_gaps(tmp_path)
    ll = _lifeloop(tmp_path, field, runner=_ok_runner)
    out = ll.tick(mem_client=None)
    web_tasks = [t for t in ll.tasks.list() if "web" in (t.get("allowed_sources") or [])]
    assert web_tasks, "a web gap task should have been created"
    for t in web_tasks:
        assert t["status"] == BLOCKED_NEEDS_PERMISSION       # blocked, never auto-run
        assert t["task_id"] not in [r["task_id"] for r in out["tasks_run"]]


def test_lifeloop_relation_maintenance_never_answers_user(tmp_path):
    ll = _lifeloop(tmp_path, _field_with_gaps(tmp_path), runner=_ok_runner)
    out = ll.tick(mem_client=None)
    assert "answer" not in out                               # tick never produces a user answer
    assert ll.status_v2()["answers_user_directly"] is False
    assert ll.status_v2()["is_truth_authority"] is False


def test_self_state_snapshot_includes_relation_maintenance(tmp_path):
    ll = _lifeloop(tmp_path, _field_with_gaps(tmp_path))
    ll.tick(mem_client=None)
    snap = ll.write_self_state_snapshot(None)
    assert "relation_maintenance" in snap
    assert snap["relation_maintenance"] is not None


def test_lifeloop_respects_max_tasks_per_tick(tmp_path):
    ll = _lifeloop(tmp_path, _field_with_gaps(tmp_path, extra_candidates=3), runner=_ok_runner)
    ll.max_tasks_per_tick = 1
    out = ll.tick(mem_client=None)
    assert len(out["tasks_run"]) <= 1                        # bounded ops per tick
