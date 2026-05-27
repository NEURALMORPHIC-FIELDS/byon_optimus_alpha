"""Tests for BYONLifeLoop v1 - internal circulation, no memory authority."""
from __future__ import annotations

import importlib

ll = importlib.import_module("gateway.lifeloop")


class FakeMem:
    def __init__(self):
        self.consolidated = 0
        self.stored = []  # must stay empty: LifeLoop holds NO memory authority

    def fce_consolidate(self):
        self.consolidated += 1
        return {"fce_status": "consolidated"}

    def store_fact(self, *a, **k):  # presence only; LifeLoop must never call it
        self.stored.append((a, k))
        return {"success": True}


def _loop(tmp_path, **kw):
    return ll.BYONLifeLoop(events_path=str(tmp_path / "events.jsonl"), **kw)


def test_event_stream_and_self_state(tmp_path):
    L = _loop(tmp_path)
    L.record_interaction(question="q1", status="KNOWN")
    L.record_interaction(question="q2", status="UNKNOWN")
    s = L.snapshot()
    assert s["interactions"] == 2 and s["known"] == 1 and s["unknown"] == 1
    assert s["unknown_rate"] == 0.5
    assert (tmp_path / "events.jsonl").exists()


def test_repetition_tracking(tmp_path):
    L = _loop(tmp_path)
    L.record_interaction(question="same question", status="UNKNOWN")
    L.record_interaction(question="same question", status="UNKNOWN")
    assert L.snapshot()["repetitions"] == 1


def test_feedback_pressure_up_and_down(tmp_path):
    L = _loop(tmp_path)
    L.record_feedback(rating="wrong")
    p1 = L.snapshot()["feedback_pressure"]
    assert p1 >= 1.5
    L.record_feedback(rating="right")
    assert L.snapshot()["feedback_pressure"] < p1


def test_consolidate_triggers_after_n_interactions(tmp_path):
    L = _loop(tmp_path, consolidate_every=3, pressure_threshold=100.0)
    for i in range(2):
        L.record_interaction(question=f"q{i}", status="KNOWN")
    assert L.should_consolidate() is False
    L.record_interaction(question="q2", status="KNOWN")
    assert L.should_consolidate() is True
    mem = FakeMem()
    out = L.tick(mem)
    assert out["consolidated"] is True and mem.consolidated == 1
    assert L.snapshot()["interactions_since_consolidate"] == 0  # reset after consolidation


def test_feedback_pressure_triggers_consolidation(tmp_path):
    L = _loop(tmp_path, consolidate_every=1000, pressure_threshold=2.0)
    L.record_feedback(rating="wrong")   # +1.5
    L.record_feedback(rating="wrong")   # +1.5 -> 3.0 >= 2.0
    assert L.should_consolidate() is True
    mem = FakeMem()
    L.tick(mem)
    assert mem.consolidated == 1


def test_lifeloop_holds_no_memory_authority(tmp_path):
    """LifeLoop must never write facts/truth - it only triggers the canonical consolidation."""
    L = _loop(tmp_path, consolidate_every=1)
    L.record_interaction(question="q", status="UNKNOWN")
    mem = FakeMem()
    L.tick(mem)
    assert mem.stored == []  # no store_fact ever called by the loop
    assert "memory-service" in L.snapshot()["memory_authority"]


def test_tick_without_mem_is_safe(tmp_path):
    L = _loop(tmp_path, consolidate_every=1)
    L.record_interaction(question="q", status="KNOWN")
    out = L.tick(None)  # no backend mem (e.g., local-dev) - must not crash
    assert out["consolidated"] is True and out["result"] is None
