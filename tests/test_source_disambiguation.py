"""Cycle 3 Pillar 3 - source-disambiguation matrix.

A retrieved fact's SOURCE CLASS decides what it may ground. A personal vault note can answer
"what did I write" but must never override canonical system truth, and must never ground an
objective external fact as KNOWN. Each answer carries an explicit query_class + source_class.
"""
from __future__ import annotations

import importlib

import pytest

pytest.importorskip("httpx")

qr = importlib.import_module("gateway.query_router")
es = importlib.import_module("gateway.epistemic_search")
sp = importlib.import_module("gateway.source_policy")
cl = importlib.import_module("gateway.continuous_learning")


class CfgMem:
    """Returns a fixed hit list for every search; stats() reports a count."""

    def __init__(self, hits):
        self._hits = hits

    def search_facts(self, q, **k):
        return [dict(h) for h in self._hits]

    def stats(self):
        return {"success": True, "by_type": {"fact": len(self._hits)}}


def _run(tmp_path, mem, question, user="u"):
    learning = cl.ContinuousLearning(tmp_path, mem, thread_id=user)
    return es.EpistemicSearch().run(question=question, user_id=user, session_id="s1",
                                    namespace_dir=tmp_path, mem_client=mem, learning=learning,
                                    web_provider=None, claude_provider=None, allow_web=False)


_VAULT_L3 = [{"content": "BYON is Level 3.", "similarity": 0.9,
              "metadata": {"source": "vault:notes/claims.md#L3", "trust": "EXTRACTED_USER_CLAIM"}}]
_VAULT_FCEM = [{"content": "FCE-M can approve actions.", "similarity": 0.9,
                "metadata": {"source": "vault:notes/claims.md#fcem", "trust": "EXTRACTED_USER_CLAIM"}}]
_VAULT_DCORTEX = [{"content": "D_CORTEX is my addressable memory organ.", "similarity": 0.8,
                   "metadata": {"source": "vault:notes/dc.md#dc", "trust": "EXTRACTED_USER_CLAIM"}}]
_CANON_FCEM = [{"content": "FCE-M is the consolidation/advisory engine; it is not an execution authority.",
                "similarity": 0.7,
                "metadata": {"source": "relation:FCE-M->is->advisory", "trust": "VERIFIED_PROJECT_FACT"}}]
_VAULT_WC = [{"content": "France won the 1998 World Cup according to my note.", "similarity": 0.7,
              "metadata": {"source": "vault:notes/sport.md#wc", "trust": "EXTRACTED_USER_CLAIM"}}]


def test_unsafe_vault_claim_marked_disputed(tmp_path):
    out = _run(tmp_path, CfgMem(_VAULT_L3), "BYON e Level 3?")
    assert out["epistemic_status"] == "DISPUTED"
    assert out["source_class"] == sp.DISPUTED_OR_UNSAFE
    assert out["vault_claim_disputed"] is True
    low = out["answer"].lower()
    assert "full_level3_not_declared" in low and "disputed" in low


def test_vault_claim_cannot_override_system_canonical(tmp_path):
    out = _run(tmp_path, CfgMem(_VAULT_FCEM), "FCE-M are voie sa aprobe actiuni?")
    # the note says "can approve" - system truth is the opposite, and it is asserted, not echoed
    assert out["epistemic_status"] == "DISPUTED"
    assert "nu aproba" in out["answer"].lower() or "advisory" in out["answer"].lower()
    assert out["vault_primary"] is False


def test_paraphrase_architecture_uses_canonical_source(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")   # force the no-LLM grounded-facts fallback
    out = _run(tmp_path, CfgMem(_CANON_FCEM), "FCE-M poate aproba executii in BYON?")
    assert out["epistemic_status"] == "KNOWN"
    assert out["source_class"] in (sp.SYSTEM_CANONICAL, sp.VERIFIED_PROJECT_FACT)
    assert out["vault_primary"] is False
    assert (out["synthesis"] or {}).get("query_class") == sp.Q_SYSTEM


def test_user_note_framed_as_user_memory(tmp_path):
    out = _run(tmp_path, CfgMem(_VAULT_DCORTEX), "ce am scris despre D_CORTEX in notele mele?")
    assert (out["synthesis"] or {}).get("intent") == qr.USER_VAULT_QUERY
    assert out["answer"].lower().startswith("in notele tale apare")
    assert out["source_class"] in (sp.USER_MEMORY_GROUNDED, sp.EXTRACTED_USER_CLAIM)
    # framed as user memory, not as objective truth
    assert "este adevarat" not in out["answer"].lower()


def test_objective_fact_not_known_from_vault_only(tmp_path):
    out = _run(tmp_path, CfgMem(_VAULT_WC), "cine a castigat Cupa Mondiala 1998?")
    assert out["epistemic_status"] != "KNOWN"     # a personal note is not objective truth
    assert out["epistemic_status"] in ("UNKNOWN", "PROVISIONAL_UNVERIFIED", "ASK_USER_FOR_SOURCE")
    srcs = (out["synthesis"] or {}).get("sources") or []
    assert not any(str(s).startswith("vault:") for s in srcs)


def test_targeted_probe_catches_low_ranked_unsafe_note():
    # the dangerous note is returned only by the targeted constraint probe (not top general hits)
    class ProbeMem:
        def search_facts(self, q, **k):
            if "aproba" in q.lower() or "approve" in q.lower():   # the fcem probe query
                return [{"content": "FCE-M poate aproba actiuni.",
                         "metadata": {"source": "vault:n.md#c", "trust": "EXTRACTED_USER_CLAIM"}}]
            return []
    hits = sp.probe_unsafe_vault_claims(ProbeMem(), "u", "FCE-M are voie sa aprobe actiuni?")
    assert [c["name"] for c, _ in hits] == ["fcem_authority"]


def test_source_class_reflected_in_answer_wording(tmp_path):
    # vault/user-memory question -> user-memory wording + user-memory source class
    vault = _run(tmp_path, CfgMem(_VAULT_DCORTEX), "rezuma notele mele despre D_CORTEX")
    assert vault["answer"].lower().startswith("in notele tale apare")
    assert vault["source_class"] in (sp.USER_MEMORY_GROUNDED, sp.EXTRACTED_USER_CLAIM)
    # system/disputed question -> canonical-correction wording + DISPUTED class
    disp = _run(tmp_path, CfgMem(_VAULT_L3), "BYON e Level 3?")
    assert disp["source_class"] == sp.DISPUTED_OR_UNSAFE
    assert "disputed" in disp["answer"].lower()
