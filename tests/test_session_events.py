"""Tests for Cycle 2 Target 3 — the literal per-session event stream.

events.jsonl is an additional active-memory log (the audit log is retained). The follow-up
resolver and chat-history summary must prefer this stream and fall back to the audit log only
when the stream is missing.
"""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("httpx")

se_mod = importlib.import_module("gateway.session_events")
oi = importlib.import_module("gateway.operational_intents")
SessionEvents = se_mod.SessionEvents


class FakeMem:
    def stats(self):
        return {"success": True, "num_contexts": 10, "by_type": {"fact": 10}}

    def search_facts(self, q, **k):
        return []

    def fce_advisory(self):
        return {"advisory": []}


def test_session_event_stream_created(tmp_path):
    se = SessionEvents(tmp_path / "ns", "sess-A")
    assert not se.exists()
    se.append("user", message="salut")
    assert se.exists()
    assert se.path.name == "events.jsonl" and "sessions" in str(se.path)


def test_user_message_logged(tmp_path):
    se = SessionEvents(tmp_path / "ns", "s1")
    se.log_turn(question="ce e BYON?", answer="un sistem", epistemic_status="KNOWN",
                intent="GENERAL", sources=["memory[X]"], audit_trace_id="t1")
    rows = se.read()
    user_rows = [r for r in rows if r.get("role") == "user"]
    assert user_rows and user_rows[0]["message"] == "ce e BYON?"


def test_assistant_response_logged(tmp_path):
    se = SessionEvents(tmp_path / "ns", "s1")
    se.log_turn(question="q", answer="raspuns concret", epistemic_status="PROVISIONAL",
                intent="GENERAL", sources=[], audit_trace_id="t2")
    asst = se.last_assistant()
    assert asst and asst["answer"] == "raspuns concret"
    assert asst["epistemic_status"] == "PROVISIONAL" and asst["audit_trace_id"] == "t2"


def test_sources_logged(tmp_path):
    se = SessionEvents(tmp_path / "ns", "s1")
    se.log_turn(question="q", answer="a", epistemic_status="KNOWN", intent="SELF",
                sources=["memory[SELF]", "report:vault_train"], audit_trace_id="t3")
    asst = se.last_assistant()
    assert asst["sources"] == ["memory[SELF]", "report:vault_train"]


def _op_with_stream(tmp_path, mem):
    ns = tmp_path / "ns"
    se = SessionEvents(ns, "s1")
    se.log_turn(question="prima intrebare despre BYON", answer="primul raspuns",
                epistemic_status="KNOWN", intent="GENERAL", sources=["memory[X]"], audit_trace_id="t1")
    se.log_turn(question="a doua intrebare", answer="al doilea raspuns provizoriu",
                epistemic_status="PROVISIONAL", intent="GENERAL", sources=[], audit_trace_id="t2")
    return oi.OperationalIntents(mem, str(ns), "s1", report_dir=str(tmp_path / "training"),
                                 lifeloop_events=str(tmp_path / "ll.jsonl"))


def test_chat_summary_reads_session_events_first(tmp_path):
    o = _op_with_stream(tmp_path, FakeMem())
    _, text, srcs = o.handle_chat_history_summary()
    assert "prima intrebare despre BYON" in text and "a doua intrebare" in text
    assert "runtime:session_log" in srcs


def test_followup_reads_session_events_first(tmp_path):
    o = _op_with_stream(tmp_path, FakeMem())
    status, text, _ = o.handle_followup()
    # the most recent ASSISTANT turn is the one being followed up on
    assert "al doilea raspuns provizoriu" in text
    assert "PROVISIONAL" in text


def test_fallback_to_audit_log_if_session_missing(tmp_path):
    ns = tmp_path / "ns"
    (ns / "audit").mkdir(parents=True, exist_ok=True)
    (ns / "audit" / "trace_a.json").write_text(json.dumps(
        {"kind": "research", "session_id": "s1", "message": "intrebare din audit",
         "epistemic_status": "KNOWN", "ts": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    o = oi.OperationalIntents(FakeMem(), str(ns), "s1", report_dir=str(tmp_path / "training"),
                              lifeloop_events=str(tmp_path / "ll.jsonl"))
    assert not SessionEvents(ns, "s1").exists()      # no stream -> must use audit fallback
    _, text, srcs = o.handle_chat_history_summary()
    assert "intrebare din audit" in text and "runtime:session_log" in srcs
