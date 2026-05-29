# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Cycle 15 GATE 2 - bounded LifeLoop run: maintenance ran, a memory-only gap task auto-ran, a web
gap task did NOT auto-run, and the Cycle-14 memory-service guard skips maintenance when down."""
from __future__ import annotations

from gateway.lifeloop import BYONLifeLoop
from gateway.relation_field import RelationField
from gateway.research_tasks import BLOCKED_NEEDS_PERMISSION, DONE


class HealthyMem:
    def health(self):
        return {"_reachable": True}

    def fce_consolidate(self):
        return {"fce_status": "consolidated"}


class DownMem:
    def health(self):
        return {"_reachable": False}


def _field(tmp_path):
    f = RelationField(str(tmp_path / "rf"))
    f.add_relation("ConceptA", "depends_on", "ConceptB", source_id="r:mem",
                   source_class="DOMAIN_VERIFIED")            # candidate -> memory gap
    f.add_relation("ConceptC", "depends_on", "ConceptD", source_id="r:web",
                   source_class="PROVISIONAL_WEB")            # -> web gap (blocked)
    return f


def _runner(task):
    return {"epistemic_status": "PROVISIONAL", "answer_summary": "internal evidence",
            "sources_used": ["memory"], "stored_as": "candidate"}


def test_gate2_bounded_lifeloop_run(tmp_path):
    field = _field(tmp_path)
    ll = BYONLifeLoop(events_path=str(tmp_path / "ll" / "e.jsonl"), runtime_dir=str(tmp_path / "ll"))
    ll.maintenance_every_ticks = 1
    ll.gap_scan_every_ticks = 1
    ll.set_relation_field_provider(lambda: field)
    ll.set_task_runner(_runner)

    crashes = 0
    ran_memory_task = False
    for _ in range(3):                                        # a few bounded ticks
        try:
            out = ll.tick(mem_client=HealthyMem())
        except Exception:
            crashes += 1
            continue
        if out["tasks_run"]:
            ran_memory_task = True

    # 1) maintenance ran
    assert ll.last_relation_maintenance is not None
    # 2) a memory-only gap task auto-ran (reached DONE)
    assert ran_memory_task
    assert any(t["status"] == DONE for t in ll.tasks.list() if t["topic"].startswith("relgap:"))
    # 3) a web gap task was created but did NOT auto-run (stays blocked, needs permission)
    web_tasks = [t for t in ll.tasks.list() if "web" in (t.get("allowed_sources") or [])]
    assert web_tasks and all(t["status"] == BLOCKED_NEEDS_PERMISSION for t in web_tasks)
    # 4) zero memory-service crashes during the bounded run (Cycle 14 guard active)
    assert crashes == 0


def test_gate2_maintenance_skipped_when_memory_service_down(tmp_path):
    field = _field(tmp_path)
    ll = BYONLifeLoop(events_path=str(tmp_path / "ll2" / "e.jsonl"), runtime_dir=str(tmp_path / "ll2"))
    ll.maintenance_every_ticks = 1
    ll.gap_scan_every_ticks = 1
    ll.set_relation_field_provider(lambda: field)
    out = ll.tick(mem_client=DownMem())                       # memory-service down
    assert ll.last_relation_maintenance is None               # maintenance did NOT run
    assert out["relation_cycle"]["skipped"]                   # skipped, no fabrication
