"""Cycle 7 — autonomous memory-only task execution, result ingestion, pressure decay/priority."""
from __future__ import annotations

import importlib
import json
import time

import pytest

pytest.importorskip("httpx")

ll = importlib.import_module("gateway.lifeloop")
pr = importlib.import_module("gateway.pressure")
rt = importlib.import_module("gateway.research_tasks")


class FakeMem:
    def fce_consolidate(self):
        return {"fce_status": "consolidated"}

    def vault_fact_count(self, owner, **k):
        return {"active": 10, "tombstoned": 2}

    read_consistency_mode = "in_engine_rw_lock"


def _life(tmp_path, runner=None, **kw):
    L = ll.BYONLifeLoop(events_path=str(tmp_path / "events.jsonl"), **kw)
    if runner is not None:
        L.set_task_runner(runner)
    return L


def _candidate_runner(status="PROVISIONAL", sources=None):
    calls = []

    def runner(task):
        calls.append(task["task_id"])
        return {"epistemic_status": status, "answer_summary": f"summary for {task['topic']}",
                "sources_used": sources if sources is not None else ["memory[X]"],
                "confidence": 0.5, "candidate_id": "cand_" + task["topic"][:6],
                "stored_as": "disputed" if status == "DISPUTED" else "candidate"}
    return runner, calls


# ---------------- T2 autonomous execution ----------------
def test_memory_only_task_auto_runs_on_tick(tmp_path):
    runner, calls = _candidate_runner()
    L = _life(tmp_path, runner=runner)
    t = L.tasks.create(topic="open topic", question="what about open topic?",
                       allowed_sources=["memory", "vault", "self_state"])
    L.tick(FakeMem())
    assert calls == [t["task_id"]]
    assert L.tasks.get(t["task_id"])["status"] == "done"


def test_web_task_stays_blocked_until_permission(tmp_path, monkeypatch):
    monkeypatch.delenv("BYON_ALLOW_AUTONOMOUS_WEB", raising=False)
    runner, calls = _candidate_runner()
    L = _life(tmp_path, runner=runner)
    L.tasks.create(topic="webby", question="needs web?", allowed_sources=["memory", "web"])
    L.tick(FakeMem())
    assert calls == []                                   # web task never auto-runs
    assert L.tasks.list()[0]["status"] == "blocked_needs_permission"


def test_secret_task_never_runs(tmp_path):
    runner, calls = _candidate_runner()
    L = _life(tmp_path, runner=runner)
    assert L.tasks.create(topic="[secret]", question="my password?", is_secret=True) is None
    L.tick(FakeMem())
    assert calls == []


def test_task_result_stored_as_candidate_not_truth(tmp_path):
    runner, _ = _candidate_runner(status="PROVISIONAL")
    L = _life(tmp_path, runner=runner)
    L.tasks.create(topic="t", question="t?", allowed_sources=["memory"])
    L.tick(FakeMem())
    res = json.loads((tmp_path / "task_results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert res["stored_as"] == "candidate" and res["epistemic_status"] != "KNOWN"


def test_task_execution_log_written(tmp_path):
    runner, _ = _candidate_runner()
    L = _life(tmp_path, runner=runner)
    L.tasks.create(topic="t", question="t?", allowed_sources=["memory"])
    L.tick(FakeMem())
    assert (tmp_path / "task_execution_log.jsonl").exists()
    assert (tmp_path / "task_results.jsonl").exists()


def test_duplicate_task_not_rerun_needlessly(tmp_path):
    runner, calls = _candidate_runner()
    L = _life(tmp_path, runner=runner)
    L.tasks.create(topic="t", question="t?", allowed_sources=["memory"])
    L.tick(FakeMem())
    L.tick(FakeMem())                                    # second tick: task already done
    assert len(calls) == 1


# ---------------- T3 task result ingestion ----------------
def test_task_result_has_sources(tmp_path):
    runner, _ = _candidate_runner(sources=["memory[A]", "vault:n.md#h"])
    L = _life(tmp_path, runner=runner)
    L.tasks.create(topic="t", question="t?", allowed_sources=["memory"])
    L.tick(FakeMem())
    assert L.last_task_result["sources_used"] == ["memory[A]", "vault:n.md#h"]


def test_disputed_task_result_marked_disputed(tmp_path):
    runner, _ = _candidate_runner(status="DISPUTED")
    L = _life(tmp_path, runner=runner)
    L.record_interaction(question="contested topic", status="UNKNOWN")
    L.record_interaction(question="contested topic", status="UNKNOWN")  # -> creates task
    task = L.tasks.pending()[0]
    L.tick(FakeMem())
    assert L.last_task_result["stored_as"] == "disputed"
    assert (L.pressure.get(task["topic"]) or {}).get("disputed_count", 0) >= 1


# ---------------- T4 pressure decay / priority ----------------
def test_pressure_decays_over_time(tmp_path):
    p = pr.PressureModel(path=str(tmp_path / "p.json"))
    p.observe(topic="t", status="DISPUTED")              # +2
    p.topics["t"]["last_seen_ts"] = time.time() - 3600   # 1 hour ago
    p.decay(rate_per_hour=0.5)
    assert p.get("t")["pressure"] == 1.5                 # 2 - 0.5*1h


def test_successful_task_reduces_pressure(tmp_path):
    p = pr.PressureModel(path=str(tmp_path / "p.json"))
    p.observe(topic="t", status="DISPUTED")              # 2
    p.task_outcome(topic="t", success=True)
    assert p.get("t")["pressure"] == 1.0 and p.get("t")["success_count"] == 1


def test_failed_task_increases_pressure(tmp_path):
    p = pr.PressureModel(path=str(tmp_path / "p.json"))
    p.observe(topic="t", status="UNKNOWN")               # 1
    p.task_outcome(topic="t", success=False)
    assert p.get("t")["pressure"] == 2.0 and p.get("t")["fail_count"] == 1


def test_cancelled_task_does_not_loop(tmp_path):
    runner, calls = _candidate_runner()
    L = _life(tmp_path, runner=runner)
    t = L.tasks.create(topic="t", question="t?", allowed_sources=["memory"])
    L.tasks.cancel(t["task_id"])
    L.tick(FakeMem())
    assert calls == []                                   # cancelled task is never drained


def test_priority_orders_tasks_correctly(tmp_path):
    p = pr.PressureModel(path=str(tmp_path / "p.json"))
    p.observe(topic="hot", status="DISPUTED")            # high pressure
    p.observe(topic="hot", status="UNKNOWN")
    p.observe(topic="cold", status="PROVISIONAL")        # low
    assert p.priority("hot") > p.priority("cold")


# ---------------- T5 dashboard / mark-resolved ----------------
def test_lifeloop_status_reports_task_counts(tmp_path):
    runner, _ = _candidate_runner()
    L = _life(tmp_path, runner=runner)
    L.tasks.create(topic="a", question="a?", allowed_sources=["memory"])
    L.tasks.create(topic="b", question="b?", allowed_sources=["memory", "web"])  # blocked
    st = L.status_v2(FakeMem())
    assert "research_task_counts" in st and st["research_task_counts"]
    assert any(t["topic"] == "b" for t in st["blocked_web_tasks"])
    assert "last_auto_run_task" in st and "last_task_result" in st


def test_mark_resolved_reduces_pressure(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="annoying topic", status="DISPUTED")
    topic = pr.topic_of("annoying topic")
    assert (L.pressure.get(topic) or {}).get("pressure", 0) > 0
    L.mark_resolved(topic)
    assert L.pressure.get(topic)["pressure"] == 0.0
