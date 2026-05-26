"""Tests for the BYON Operational Intent Layer (runtime state / actions, never vault)."""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("httpx")

qr = importlib.import_module("gateway.query_router")
oi = importlib.import_module("gateway.operational_intents")
es = importlib.import_module("gateway.epistemic_search")
cl = importlib.import_module("gateway.continuous_learning")


class FakeMem:
    def __init__(self, facts=3810):
        self._facts = facts
        self.consolidated = 0

    def stats(self):
        return {"success": True, "num_contexts": self._facts, "by_type": {"fact": self._facts}}

    def search_facts(self, q, **k):
        # canonical relation/repo facts for proof; a vault note must NEVER be chosen by op intents
        return [{"content": "BYON has component D_Cortex", "similarity": 0.8,
                 "metadata": {"source": "relation:BYON->has_component->D_Cortex",
                              "trust": "VERIFIED_PROJECT_FACT"}}]

    def fce_consolidate(self):
        self.consolidated += 1
        return {"fce_status": "consolidated"}

    def fce_advisory(self):
        return {"advisory": []}


def _reports(tmp_path, vault_files=2, partial=False, notes_total=69):
    d = tmp_path / "training"
    d.mkdir(parents=True, exist_ok=True)
    (d / "self_train_report.json").write_text(json.dumps(
        {"files": 21, "chunks_stored": 179, "relations_stored": 12}), encoding="utf-8")
    (d / "vault_train_report.json").write_text(json.dumps(
        {"files": vault_files, "notes_total": notes_total, "chunks_stored": 3, "partial": partial}),
        encoding="utf-8")
    return str(d)


def _op(tmp_path, mem, session="s1", with_session_log=True):
    ns = tmp_path / "ns"
    (ns / "audit").mkdir(parents=True, exist_ok=True)
    if with_session_log:
        (ns / "audit" / "trace_a.json").write_text(json.dumps(
            {"kind": "research", "session_id": "s1", "message": "descrie BYON",
             "epistemic_status": "KNOWN", "ts": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    o = oi.OperationalIntents(mem, str(ns), session, report_dir=_reports(tmp_path),
                              lifeloop_events=str(tmp_path / "ll.jsonl"))
    return o


def test_dynamics_report_does_not_use_vault_note(tmp_path):
    status, text, srcs = _op(tmp_path, FakeMem()).handle_self_dynamics_report()
    assert status == "SELF_STATE_GROUNDED"
    assert "vault:" not in text and "Jurnal intern" not in text
    assert "3810" in text and "runtime:self_state" in srcs


def test_proof_query_runs_probe_report_not_slogan(tmp_path):
    status, text, _ = _op(tmp_path, FakeMem()).handle_self_proof()
    assert "probe" in text.lower() and "secret guard" in text.lower()
    assert "committed fact" in text.lower() and "facts indexed" in text.lower()


def test_chat_summary_uses_session_log_not_vault(tmp_path):
    status, text, srcs = _op(tmp_path, FakeMem()).handle_chat_history_summary()
    assert "runtime:session_log" in srcs and "descrie BYON" in text
    assert not any("vault" in s for s in srcs)


def test_chat_summary_no_session_log(tmp_path):
    _, text, srcs = _op(tmp_path, FakeMem(), with_session_log=False).handle_chat_history_summary()
    assert "nu exista" in text.lower() or "no chat" in text.lower()
    assert "runtime:session_log" in srcs


def test_memory_action_consolidate_calls_fce(tmp_path):
    mem = FakeMem()
    status, text, srcs = _op(tmp_path, mem).handle_memory_action("consolideaza memoria")
    assert status == "ACTION_DONE" and mem.consolidated == 1
    assert "fce:consolidate_result" in srcs


def test_memory_action_train_vault_reports_status_not_fake(tmp_path):
    mem = FakeMem()
    status, text, _ = _op(tmp_path, mem).handle_memory_action("antreneaza-te pe datele din vault")
    assert status == "ACTION_REQUIRED" and mem.consolidated == 0  # did NOT pretend it ran
    assert "--train-vault" in text


def test_followup_uses_last_response_context(tmp_path):
    _, text, srcs = _op(tmp_path, FakeMem()).handle_followup()
    assert "descrie BYON" in text and "runtime:session_log" in srcs


def test_followup_without_context_asks(tmp_path):
    status, text, _ = _op(tmp_path, FakeMem(), with_session_log=False).handle_followup()
    assert status == "ASK_USER_FOR_SOURCE"


def test_saved_memory_wording_maps_to_self_memory_state():
    for q in ["ce este in memoria ta salvat?", "ce ai salvat in memorie?", "ce s-a pastrat in memorie?",
              "ce ai stocat?", "ce contine memoria ta?"]:
        assert qr.classify_intent(q) == qr.SELF_MEMORY_STATE_QUERY


def test_vault_training_status_detects_stale_report(tmp_path):
    # report says 2 notes but memory has many facts -> stale/partial
    _, text, _ = _op(tmp_path, FakeMem(facts=3810)).handle_vault_training_status()
    assert "stale" in text.lower() or "partial" in text.lower()
    assert "--train-vault" in text


def test_operational_intents_preempt_generic_vault_retrieval(tmp_path, monkeypatch):
    """The live loop must route an operational command to the operational layer BEFORE any
    memory/vault search."""
    import gateway.operational_intents as oimod
    orig = oimod.OperationalIntents

    def factory(mem, ns, session, **k):
        return orig(mem, ns, session, report_dir=_reports(tmp_path),
                    lifeloop_events=str(tmp_path / "ll.jsonl"))
    monkeypatch.setattr(oimod, "OperationalIntents", factory)

    mem = FakeMem()
    learning = cl.ContinuousLearning(tmp_path, mem, thread_id="u")
    out = es.EpistemicSearch().run(question="ruleaza o analiza reala a dinamicii tale interne",
                                   user_id="u", session_id="s1", namespace_dir=tmp_path,
                                   mem_client=mem, learning=learning, web_provider=None,
                                   claude_provider=None, allow_web=False)
    assert out["epistemic_status"] == "SELF_STATE_GROUNDED"
    assert "vault:" not in out["answer"]
    assert out["synthesis"]["intent"] == qr.SELF_DYNAMICS_REPORT_QUERY
