"""Tests for continuous learning as an interaction side-effect (over the memory-service)."""
from __future__ import annotations

import importlib
import json

cl = importlib.import_module("gateway.continuous_learning")


class FakeMem:
    def __init__(self):
        self.stored = []
        self.consolidated = 0

    def store_fact(self, fact, **kw):
        self.stored.append({"fact": fact, **kw})
        return {"success": True}

    def fce_consolidate(self):
        self.consolidated += 1
        return {"fce_status": "consolidated"}


def test_interaction_event_always_logged(tmp_path):
    mem = FakeMem()
    c = cl.ContinuousLearning(tmp_path, mem, thread_id="u")
    c.record_event("chat", question="hi", status="UNKNOWN")
    rows = [json.loads(l) for l in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["kind"] == "chat" and rows[-1]["status"] == "UNKNOWN"


def test_learning_side_effect_stores_web_candidate(tmp_path):
    mem = FakeMem()
    c = cl.ContinuousLearning(tmp_path, mem, thread_id="u")
    cand = c.store_web_candidate("France", ["https://fifa.com/1998"], question="who won 1998?")
    assert cand["evidence_count"] == 1 and cand["status"] == "candidate"
    # written to candidate ledger AND mirrored into memory-service as an uncommitted fact
    assert c.list_candidates()[0]["value"] == "France"
    assert any(s["fact"] == "France" and s.get("trust") is None for s in mem.stored)


def test_user_acceptance_reinforces_candidate(tmp_path):
    mem = FakeMem()
    c = cl.ContinuousLearning(tmp_path, mem, thread_id="u")
    c.store_web_candidate("France", ["https://fifa.com/1998"])
    c.reinforce("France")
    assert c.list_candidates()[0]["evidence_count"] == 2


def test_consolidation_commits_repeated_evidence(tmp_path):
    mem = FakeMem()
    c = cl.ContinuousLearning(tmp_path, mem, thread_id="u")
    c.store_web_candidate("France", ["https://fifa.com/1998"])
    c.reinforce("France")  # evidence_count = 2 (>= threshold default 2)
    out = c.consolidate(threshold=2)
    assert "France" in out["promoted"]
    assert mem.consolidated == 1
    # promoted into memory-service with a committed trust tier
    assert any(s["fact"] == "France" and s.get("trust") == "VERIFIED_PROJECT_FACT" for s in mem.stored)
    assert c.list_committed() and not c.list_candidates()  # moved out of candidates


def test_dispute_marks_disputed(tmp_path):
    mem = FakeMem()
    c = cl.ContinuousLearning(tmp_path, mem, thread_id="u")
    c.dispute("France", reason="contradiction")
    assert c.list_disputed()[0]["value"] == "France"
    assert any(s.get("disputed") for s in mem.stored)
