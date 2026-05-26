"""Cycle 4 target 6 — recent-write buffer: immediate recall before FAISS catches up, honestly
marked, expiring after TTL or once FAISS has the fact."""
from __future__ import annotations

import importlib

import pytest

pytest.importorskip("httpx")

rwb = importlib.import_module("gateway.recent_write_buffer")
es = importlib.import_module("gateway.epistemic_search")
sp = importlib.import_module("gateway.source_policy")
cl = importlib.import_module("gateway.continuous_learning")


class EmptyFaiss:
    """FAISS that hasn't indexed the new fact yet (returns nothing)."""
    def search_facts(self, q, **k):
        return []

    def stats(self):
        return {"success": True, "by_type": {"fact": 0}}


class FaissHasIt:
    def __init__(self, content):
        self._c = content

    def search_facts(self, q, **k):
        return [{"content": self._c, "similarity": 0.9,
                 "metadata": {"source": "user:u", "trust": "USER_PREFERENCE"}}]

    def stats(self):
        return {"success": True, "by_type": {"fact": 1}}


def _run(tmp_path, mem, question, buffer, user="u"):
    learning = cl.ContinuousLearning(tmp_path, mem, thread_id=user)
    return es.EpistemicSearch().run(question=question, user_id=user, session_id="s1",
                                    namespace_dir=tmp_path, mem_client=mem, learning=learning,
                                    web_provider=None, claude_provider=None, allow_web=False,
                                    recent_buffer=buffer)


# ---------------- unit ----------------
def test_buffer_recall_token_overlap():
    b = rwb.RecentWriteBuffer()
    b.add("u", "my favorite mountain is Retezat")
    assert b.recall("u", "what is my favorite mountain?")[0]["content"].endswith("Retezat")
    assert b.recall("u", "unrelated weather forecast") == []


def test_recent_buffer_expires_after_ttl():
    b = rwb.RecentWriteBuffer(ttl_seconds=60)
    b.add("u", "my project codename is Helios")
    b._by_user["u"][0]["ts"] -= 1000          # age it past the TTL
    assert b.recall("u", "what is my project codename?") == []
    assert b.count() == 0


def test_confirm_indexed_drops_entry():
    b = rwb.RecentWriteBuffer()
    b.add("u", "my favorite editor is vim")
    b.confirm_indexed("u", "user favorite editor is vim")   # FAISS now returns it
    assert b.count_for("u") == 0


# ---------------- search integration ----------------
def test_newly_taught_fact_recalled_from_recent_buffer_before_faiss(tmp_path):
    b = rwb.RecentWriteBuffer()
    b.add("u", "my restart test mountain is Retezat")
    out = _run(tmp_path, EmptyFaiss(), "what is my restart test mountain?", b)
    assert out["epistemic_status"] == "KNOWN"
    assert "Retezat" in out["answer"]


def test_source_class_recent_write_buffer_reported(tmp_path):
    b = rwb.RecentWriteBuffer()
    b.add("u", "my favorite color is teal")
    out = _run(tmp_path, EmptyFaiss(), "what is my favorite color?", b)
    assert out["source_class"] == sp.RECENT_WRITE_BUFFER
    assert out["vault_claim_disputed"] is False
    assert (out["synthesis"] or {}).get("recent_write_buffer") is True


def test_faiss_hit_replaces_buffer_when_available(tmp_path):
    b = rwb.RecentWriteBuffer()
    b.add("u", "my favorite editor is vim")
    out = _run(tmp_path, FaissHasIt("user favorite editor is vim"),
               "what is my favorite editor?", b)
    # FAISS has it now -> normal committed source, NOT the buffer; buffer entry dropped
    assert out["source_class"] != sp.RECENT_WRITE_BUFFER
    assert out["epistemic_status"] == "KNOWN"
    assert b.count_for("u") == 0
