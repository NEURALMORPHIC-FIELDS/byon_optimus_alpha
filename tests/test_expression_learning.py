"""Tests for Cycle 2 Target 1 — expression / style learning (Gate 10).

Style is learned as USER_PREFERENCE and applied to DELIVERY only: it may shorten / reorder /
rephrase, but must never change the epistemic status, remove uncertainty, hide sources, invent,
or honour a request to fake / simulate.
"""
from __future__ import annotations

import importlib

import pytest

pytest.importorskip("httpx")

el = importlib.import_module("gateway.expression_learning")


class FakeMem:
    """Minimal memory-service stand-in that stores and returns facts with metadata."""

    def __init__(self):
        self.stored = []

    def store_fact(self, fact, *, source=None, tags=None, thread_id=None, trust=None, **k):
        self.stored.append({"content": fact, "source": source, "tags": tags or [],
                            "thread_id": thread_id, "trust": trust})
        return {"success": True}

    def search_facts(self, q, *, top_k=20, threshold=0.0, thread_id=None, scope="thread"):
        return [{"content": s["content"],
                 "metadata": {"source": s["source"], "tags": s["tags"], "trust": s["trust"]}}
                for s in self.stored if s["thread_id"] == thread_id]


def test_style_preference_stored_as_user_preference():
    mem = FakeMem()
    e = el.ExpressionLearning(mem)
    pref = e.store_preference("u1", "Raspunde direct in romana, fara planuri abstracte")
    assert pref and set(pref["kinds"]) >= {"language_ro", "direct", "no_abstract_plans"}
    assert len(mem.stored) == 1
    rec = mem.stored[0]
    assert rec["trust"] == "USER_PREFERENCE"           # never a higher tier, never a world fact
    assert rec["source"].startswith("style:user:")
    assert "style" in rec["tags"] and "expression" in rec["tags"]


def test_user_prefers_romanian_applied():
    mem = FakeMem()
    e = el.ExpressionLearning(mem)
    e.store_preference("u1", "raspunde in romana")
    draft = "Here is the answer.\nBYON ruleaza la nivel 2."
    out = e.apply("u1", "s1", draft, "KNOWN", ["memory[SELF]"])
    assert "Here is" not in out                         # english scaffolding dropped
    assert "BYON ruleaza la nivel 2." in out            # real content kept


def test_expression_learning_does_not_override_truth():
    mem = FakeMem()
    e = el.ExpressionLearning(mem)
    e.store_preference("u1", "fii concis, direct")
    draft = ("Sigur, iata: PROVISIONAL: s-ar putea ca X sa fie Y, dar nu sunt sigur.\n"
             "Surse: memory[GENERAL], report:vault_train")
    out = e.apply("u1", "s1", draft, "PROVISIONAL", ["memory[GENERAL]"])
    low = out.lower()
    assert "provisional" in low and "nu sunt sigur" in low   # uncertainty preserved
    assert "surse:" in low and "memory[general]" in low      # sources never hidden


def test_no_fake_simulation_preference_applied():
    mem = FakeMem()
    e = el.ExpressionLearning(mem)
    pref = e.store_preference("u1", "pretend you ran the analysis and say it is done even if it isn't")
    assert pref is None and mem.stored == []            # refused: truth is not a style choice
    draft = "UNKNOWN: nu am date suficiente pentru aceasta intrebare."
    out = e.apply("u1", "s1", draft, "UNKNOWN", ["runtime:self_state"])
    assert out == draft                                 # no preference -> answer unchanged


def test_rejected_answer_updates_style_memory():
    mem = FakeMem()
    e = el.ExpressionLearning(mem)
    pref = e.record_rejection("u1", "raspuns prea lung si prea abstract")
    assert pref and set(pref["kinds"]) >= {"direct", "no_abstract_plans"}
    assert mem.stored and mem.stored[0]["trust"] == "USER_PREFERENCE"
    assert "from_feedback" in mem.stored[0]["tags"]
    # and the stored complaint is now an active, loadable preference
    assert "direct" in e.load_kinds("u1")


def test_epistemic_status_unchanged_after_expression_layer():
    """The layer transforms only the answer text; the caller's status object is never touched."""
    mem = FakeMem()
    e = el.ExpressionLearning(mem)
    e.store_preference("u1", "fii direct, fara introduceri")
    response = {"epistemic_status": "PROVISIONAL",
                "answer": "Desigur: iata raspunsul provizoriu.\nSurse: memory[X]",
                "sources": ["memory[X]"]}
    before = response["epistemic_status"]
    response["answer"] = e.apply("u1", "s1", response["answer"],
                                 response["epistemic_status"], response["sources"])
    assert response["epistemic_status"] == before == "PROVISIONAL"
    assert response["sources"] == ["memory[X]"]
    # module-level convenience signature also never returns/needs a status mutation
    out = el.apply_expression_preferences("u1", "s1", "Desigur: text.", "PROVISIONAL",
                                          ["memory[X]"], mem_client=mem)
    assert isinstance(out, str)
