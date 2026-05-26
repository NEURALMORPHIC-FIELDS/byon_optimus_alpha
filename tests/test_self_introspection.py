"""Tests for self-introspection answering from runtime state (not vault)."""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("httpx")

qr = importlib.import_module("gateway.query_router")
ssp_mod = importlib.import_module("gateway.self_state_provider")
es = importlib.import_module("gateway.epistemic_search")
cl = importlib.import_module("gateway.continuous_learning")


class FakeMem:
    def __init__(self, facts=2263, vault_hit=True):
        self._facts = facts
        self._vault_hit = vault_hit

    def stats(self):
        return {"success": True, "num_contexts": self._facts, "by_type": {"fact": self._facts}}

    def search_facts(self, *a, **k):  # a high-cosine STALE vault note that must NOT be used
        if self._vault_hit:
            return [{"content": "Jurnal intern. Provisional entries never promoted (Pas 6).",
                     "similarity": 0.95,
                     "metadata": {"source": "vault:30 Sources/old.md#h", "trust": "EXTRACTED_USER_CLAIM"}}]
        return []

    def fce_consolidate(self):
        return {"fce_status": "consolidated"}


def _reports(tmp_path, vault_partial=False):
    d = tmp_path / "training"
    d.mkdir(parents=True, exist_ok=True)
    (d / "self_train_report.json").write_text(json.dumps(
        {"files": 21, "chunks_stored": 179, "relations_stored": 12,
         "trust_tiers": {"VERIFIED_PROJECT_FACT": 191}}), encoding="utf-8")
    (d / "vault_train_report.json").write_text(json.dumps(
        {"files": 69, "chunks_stored": 1500, "partial": vault_partial,
         "trust_tiers": {"EXTRACTED_USER_CLAIM": 1500}}), encoding="utf-8")
    return str(d)


def _provider(tmp_path, mem, **kw):
    return ssp_mod.SelfStateProvider(mem, report_dir=_reports(tmp_path, **kw),
                                     lifeloop_events=str(tmp_path / "none.jsonl"))


def test_capabilities_query_uses_self_state_not_vault(tmp_path):
    text, srcs = _provider(tmp_path, FakeMem()).answer_for(qr.SELF_CAPABILITY_QUERY, "ce capacitati ai?")
    assert "Jurnal intern" not in text
    # no vault RETRIEVAL source (a "report:vault_train" training report is fine, not a vault hit)
    assert "runtime:self_state" in srcs and not any(s.startswith("vault:") for s in srcs)
    assert "memory-service" in text.lower() or "FAISS" in text


def test_memory_state_query_uses_stats_reports_not_vault(tmp_path):
    text, srcs = _provider(tmp_path, FakeMem()).answer_for(qr.SELF_MEMORY_STATE_QUERY, "ce ai asimilat?")
    assert "179 chunks" in text and "21" in text and "Jurnal intern" not in text
    assert "report:self_train" in srcs


def test_stale_limitations_do_not_override_current_status(tmp_path):
    text, _ = _provider(tmp_path, FakeMem()).answer_for(qr.SELF_MEMORY_STATE_QUERY, "ce ai in memorie?")
    assert "never promoted" not in text and "Pas 6" not in text
    assert qr.is_stale_limitation("Provisional entries never promoted (Pas 6)") is True


def test_vault_note_allowed_only_for_user_vault_intent():
    assert qr.classify_intent("ce am scris in notele mele despre memoria provizorie?") == qr.USER_VAULT_QUERY
    assert qr.classify_intent("ce ai asimilat in memorie?") == qr.SELF_MEMORY_STATE_QUERY


def test_self_capabilities_do_not_claim_unimplemented_lifeloop(tmp_path):
    text, _ = _provider(tmp_path, FakeMem()).answer_for(qr.SELF_CAPABILITY_QUERY, "what can you do?")
    low = text.lower()
    assert "not consciousness" in low               # disclaims, never claims consciousness
    assert "no vision" in low                       # explicitly states the limitation
    assert "v1" in low                              # LifeLoop is v1, not full autonomy
    # the only mention of "level 3" is the explicit non-declaration
    assert "no level 3 claim" in low and "full_level3_not_declared" in low


def test_self_memory_state_reports_training_counts(tmp_path):
    text, _ = _provider(tmp_path, FakeMem(facts=3627)).answer_for(qr.SELF_MEMORY_STATE_QUERY, "ce ai invatat?")
    assert "3627" in text and "179 chunks" in text and "12" in text


def test_self_memory_state_reports_partial_vault_if_partial(tmp_path):
    text, _ = _provider(tmp_path, FakeMem(), vault_partial=True).answer_for(
        qr.SELF_MEMORY_STATE_QUERY, "ce ai asimilat?")
    assert "PARTIAL" in text


def test_self_state_mentions_full_level3_not_declared(tmp_path):
    text, _ = _provider(tmp_path, FakeMem()).answer_for(qr.SELF_CAPABILITY_QUERY, "ce capacitati ai?")
    assert "FULL_LEVEL3_NOT_DECLARED" in text


def test_current_runtime_outprioritizes_old_vault_note(tmp_path, monkeypatch):
    """The live loop answers a memory-state question from runtime state even though the mocked
    memory-service returns a high-cosine stale vault note."""
    rdir = _reports(tmp_path)
    orig = ssp_mod.SelfStateProvider

    def factory(mem_client=None, **k):
        return orig(mem_client, report_dir=rdir, lifeloop_events=str(tmp_path / "n.jsonl"))
    monkeypatch.setattr(ssp_mod, "SelfStateProvider", factory)

    mem = FakeMem(facts=3627)
    learning = cl.ContinuousLearning(tmp_path, mem, thread_id="u")
    out = es.EpistemicSearch().run(question="ce ai asimilat in memorie?", user_id="u", session_id="s",
                                   namespace_dir=tmp_path, mem_client=mem, learning=learning,
                                   web_provider=None, claude_provider=None, allow_web=False)
    assert out["epistemic_status"] == "KNOWN"
    assert out["synthesis"].get("grounding") == "SELF_STATE_GROUNDED"
    assert "Jurnal intern" not in out["answer"] and "3627" in out["answer"]
