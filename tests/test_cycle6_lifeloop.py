"""Cycle 6 — LifeLoop v2: event ingestion, pressure, research tasks, consolidation, snapshots."""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("httpx")

ll = importlib.import_module("gateway.lifeloop")
pr = importlib.import_module("gateway.pressure")
rt = importlib.import_module("gateway.research_tasks")
ssp_mod = importlib.import_module("gateway.self_state_provider")


class FakeMem:
    def __init__(self):
        self.consolidated = 0

    def fce_consolidate(self):
        self.consolidated += 1
        return {"fce_status": "consolidated"}

    def vault_fact_count(self, owner, **k):
        return {"active": 5977, "tombstoned": 4419}

    read_consistency_mode = "rw_coordinated_snapshot+retry"

    def stats(self):
        return {"by_type": {"fact": 10}}

    def fce_advisory(self):
        return {"advisory": []}


def _life(tmp_path, **kw):
    return ll.BYONLifeLoop(events_path=str(tmp_path / "events.jsonl"), **kw)


def _events(tmp_path):
    p = tmp_path / "events.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------- T1 event ingestion ----------------
def test_lifeloop_ingests_chat_event(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="ce este BYON?", status="KNOWN", user_id="u", session_id="s",
                         query_class="system", source_class="SYSTEM_CANONICAL", intent="SELF_ARCHITECTURE_QUERY",
                         sources=["memory[X]"], audit_trace_id="t1")
    ev = _events(tmp_path)[-1]
    assert ev["event_type"] == "chat" and ev["epistemic_status"] == "KNOWN"
    assert ev["query_class"] == "system" and ev["source_class"] == "SYSTEM_CANONICAL"
    assert "event_id" in ev and ev["ts"]


def test_lifeloop_ingests_feedback_event(tmp_path):
    L = _life(tmp_path)
    L.record_feedback(rating="wrong", user_id="u", question="topicX", audit_trace_id="t2")
    ev = _events(tmp_path)[-1]
    assert ev["event_type"] == "feedback" and ev["rating"] == "wrong"


def test_lifeloop_ingests_memory_action_event(tmp_path):
    L = _life(tmp_path)
    L.record_event("memory_action", topic="consolidate", user_id="u")
    ev = _events(tmp_path)[-1]
    assert ev["event_type"] == "memory_action"


def test_lifeloop_preserves_audit_trace_id(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="q", status="PROVISIONAL", audit_trace_id="trace-xyz")
    assert _events(tmp_path)[-1]["audit_trace_id"] == "trace-xyz"


def test_lifeloop_never_stores_secret_content(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="what is my bank password?", status="UNKNOWN", query_class="secret")
    ev = _events(tmp_path)[-1]
    assert "password" not in json.dumps(ev).lower()
    assert ev["question"] == "[redacted-secret]" and "secret" in ev["tags"]


# ---------------- T2 pressure ----------------
def test_unknown_increases_pressure(tmp_path):
    p = pr.PressureModel(path=str(tmp_path / "p.json"))
    p.observe(topic="cluj 1500", status="UNKNOWN")
    assert p.total() == 1.0


def test_repeated_unknown_increases_pressure_more(tmp_path):
    p = pr.PressureModel(path=str(tmp_path / "p.json"))
    p.observe(topic="t", status="UNKNOWN")
    first = p.total()
    p.observe(topic="t", status="UNKNOWN")
    assert p.total() - first > first          # the repeat adds more than the first occurrence


def test_negative_feedback_increases_pressure(tmp_path):
    p = pr.PressureModel(path=str(tmp_path / "p.json"))
    p.feedback(topic="t", rating="wrong")
    assert p.get("t")["pressure"] == 3.0 and p.get("t")["correction_count"] == 1


def test_accepted_feedback_reduces_pressure(tmp_path):
    p = pr.PressureModel(path=str(tmp_path / "p.json"))
    p.observe(topic="t", status="DISPUTED")   # +2
    p.feedback(topic="t", rating="correct")   # -1
    assert p.get("t")["pressure"] == 1.0


def test_secret_does_not_create_research_task(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="what is my password?", status="UNKNOWN")  # secret
    L.record_interaction(question="what is my password?", status="UNKNOWN")
    assert L.tasks.pending() == []            # never a research task on a secret


def test_pressure_state_persisted(tmp_path):
    path = str(tmp_path / "p.json")
    pr.PressureModel(path=path).observe(topic="t", status="DISPUTED")
    p2 = pr.PressureModel(path=path)          # reload
    assert p2.get("t")["pressure"] == 2.0


# ---------------- T3 research task queue ----------------
def test_repeated_unknown_creates_research_task(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="who won the 1998 world cup?", status="UNKNOWN")
    L.record_interaction(question="who won the 1998 world cup?", status="UNKNOWN")
    tasks = L.tasks.pending()
    assert len(tasks) == 1 and "1998 world cup" in tasks[0]["question"].lower()
    assert tasks[0]["allowed_sources"] == ["memory", "vault", "self_state"]


def test_web_task_requires_permission_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BYON_ALLOW_AUTONOMOUS_WEB", raising=False)
    q = rt.ResearchTaskQueue(path=str(tmp_path / "rt.jsonl"))
    t = q.create(topic="x", question="x?", allowed_sources=["memory", "web"])
    assert t["status"] == rt.BLOCKED_NEEDS_PERMISSION and t["requires_user_permission"] is True


def test_duplicate_task_not_created_for_same_topic(tmp_path):
    q = rt.ResearchTaskQueue(path=str(tmp_path / "rt.jsonl"))
    a = q.create(topic="same", question="same?")
    b = q.create(topic="same", question="same?")
    assert a["task_id"] == b["task_id"] and len(q.list()) == 1


def test_task_status_persisted_and_records_result(tmp_path):
    path = str(tmp_path / "rt.jsonl")
    q = rt.ResearchTaskQueue(path=path)
    t = q.create(topic="t", question="t?")
    q.set_status(t["task_id"], rt.DONE, result={"epistemic_status": "PROVISIONAL"})
    q2 = rt.ResearchTaskQueue(path=path)      # reload
    rt2 = q2.get(t["task_id"])
    assert rt2["status"] == rt.DONE and rt2["result"]["epistemic_status"] == "PROVISIONAL"


def test_secret_never_creates_research_task(tmp_path):
    q = rt.ResearchTaskQueue(path=str(tmp_path / "rt.jsonl"))
    assert q.create(topic="t", question="t?", is_secret=True) is None


# ---------------- T4 consolidation scheduler ----------------
def test_disputed_triggers_consolidation(tmp_path):
    L = _life(tmp_path, consolidate_every=999, pressure_threshold=99)
    L.record_interaction(question="x", status="DISPUTED")
    assert L.should_consolidate() is True
    mem = FakeMem()
    out = L.tick(mem)
    assert out["consolidated"] is True and mem.consolidated == 1


def test_correction_triggers_consolidation(tmp_path):
    L = _life(tmp_path, consolidate_every=999, pressure_threshold=99)
    L.record_feedback(rating="wrong", question="topic")
    assert L.should_consolidate() is True


def test_pressure_triggers_consolidation(tmp_path):
    L = _life(tmp_path, consolidate_every=999, pressure_threshold=2.0)
    L.record_interaction(question="x", status="DISPUTED")   # pressure +2 >= 2.0
    assert L.should_consolidate() is True


def test_consolidation_log_written_and_reduces_pressure(tmp_path):
    L = _life(tmp_path, consolidate_every=999, pressure_threshold=2.0)
    L.record_interaction(question="x", status="DISPUTED")
    before = L.pressure.total()
    L.tick(FakeMem())
    assert (tmp_path / "consolidation_log.jsonl").exists()
    rec = json.loads((tmp_path / "consolidation_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["fce_status"] == "consolidated" and rec["pressure_after"] < before


# ---------------- T5 self-state temporal snapshots ----------------
def test_self_state_snapshot_written(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="x", status="UNKNOWN")
    L.tick(FakeMem())
    snaps = L.recent_snapshots()
    assert snaps and "unknown_count" in snaps[-1] and snaps[-1]["active_vault_facts"] == 5977


def test_internal_pressure_answer_uses_pressure_state(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="hard topic alpha", status="DISPUTED")
    from gateway import query_router as qr
    ssp = ssp_mod.SelfStateProvider(FakeMem(), lifeloop_events=str(tmp_path / "events.jsonl"))
    text, srcs = ssp.answer_for(qr.SELF_INTERNAL_STATE_QUERY, "ce presiuni ai active?")
    assert "presiune interna totala" in text and "runtime:lifeloop:pressure" in srcs


def test_pending_tasks_answer_uses_task_queue(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="repeated objective q", status="UNKNOWN")
    L.record_interaction(question="repeated objective q", status="UNKNOWN")
    from gateway import query_router as qr
    ssp = ssp_mod.SelfStateProvider(FakeMem(), lifeloop_events=str(tmp_path / "events.jsonl"))
    text, _ = ssp.answer_for(qr.SELF_INTERNAL_STATE_QUERY, "ce sarcini interne ai in asteptare?")
    assert "sarcini interne de cercetare in asteptare: 1" in text


def test_recent_learning_answer_uses_snapshots(tmp_path):
    L = _life(tmp_path)
    L.record_interaction(question="x", status="KNOWN")
    L.tick(FakeMem())
    from gateway import query_router as qr
    ssp = ssp_mod.SelfStateProvider(FakeMem(), lifeloop_events=str(tmp_path / "events.jsonl"))
    text, _ = ssp.answer_for(qr.SELF_RECENT_LEARNING_QUERY, "ce ai invatat recent?")
    assert "ultima stare interna" in text and "snapshot tick" in text


# ---------------- routing ----------------
def test_internal_state_intent_routing():
    from gateway import query_router as qr
    for q in ["ce te preocupa intern?", "ce presiuni ai active?", "ce sarcini interne ai in asteptare?",
              "ce contradictii ai observat?"]:
        assert qr.classify_intent(q) == qr.SELF_INTERNAL_STATE_QUERY


def test_lifeloop_status_reports_v2(tmp_path):
    L = _life(tmp_path)
    st = L.status_v2(FakeMem())
    assert st["version"] == "v2" and st["answers_user_directly"] is False
    assert st["is_truth_authority"] is False
    assert st["memory_service_read_consistency_mode"] == "rw_coordinated_snapshot+retry"
