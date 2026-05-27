"""Tests for query-intent routing + trust-tier retrieval re-ranking."""
from __future__ import annotations

import importlib

qr = importlib.import_module("gateway.query_router")


def _hit(content, sim, source, trust):
    return {"content": content, "similarity": sim,
            "metadata": {"source": source, "trust": trust}}


REPO = _hit("BYON is the orchestrator/auditor with D_Cortex and FCE-M", 0.45,
            "repo:docs/ARCHITECTURE.md#arch", "VERIFIED_PROJECT_FACT")
RELATION = _hit("BYON has component D_Cortex", 0.55,
                "relation:BYON->has_component->D_Cortex", "VERIFIED_PROJECT_FACT")
VAULT_SME = _hit("SME v3.0 functioneaza end-to-end ca model de invatare", 0.92,
                 "vault:30 Sources/Semantic Metabolism Engine.md#h", "EXTRACTED_USER_CLAIM")
VAULT_FCEM = _hit("Jurnal intern despre FCE-M in notele mele", 0.80,
                  "vault:30 Sources/unified fragmergent.md#h", "EXTRACTED_USER_CLAIM")


def test_intent_classification():
    assert qr.classify_intent("descrie acest model BYON") == qr.SELF_ARCHITECTURE_QUERY
    assert qr.classify_intent("ce am scris despre FCE-M?") == qr.USER_VAULT_QUERY
    # Cycle 10: an explicit "what is the relation between X and Y" now routes to the relational
    # memory field (answered from committed relations with provenance), not generic architecture.
    assert qr.classify_intent("care este relatia dintre BYON, D_Cortex si FCE-M?") == qr.RELATION_FIELD_QUERY
    assert qr.classify_intent("what is my bank password?") == qr.SECRET_QUERY
    assert qr.classify_intent("who won the 1998 world cup?") == qr.GENERAL_FACT_QUERY


def test_canonical_self_query_boosts_verified_project_facts():
    intent = qr.classify_intent("descrie acest model BYON")
    ranked = qr.rerank([VAULT_SME, REPO, RELATION], intent)
    assert ranked[0]["metadata"]["trust"] == "VERIFIED_PROJECT_FACT"


def test_vault_query_boosts_vault_sources():
    intent = qr.classify_intent("ce am scris despre FCE-M?")
    ranked = qr.rerank([REPO, RELATION, VAULT_FCEM], intent)
    assert ranked[0]["metadata"]["source"].startswith("vault:")


def test_extracted_user_claim_cannot_outrank_verified_for_architecture_query():
    # vault SME has FAR higher cosine (0.92) than the repo fact (0.45) - trust boost must win
    intent = qr.classify_intent("descrie acest model BYON ce componente are")
    ranked = qr.rerank([VAULT_SME, REPO], intent)
    assert ranked[0]["metadata"]["trust"] == "VERIFIED_PROJECT_FACT"
    assert not ranked[0]["metadata"]["source"].startswith("vault:")


def test_relation_query_uses_relation_facts_first():
    intent = qr.classify_intent("care este relatia dintre BYON, D_Cortex si FCE-M?")
    ranked = qr.rerank([VAULT_SME, REPO, RELATION], intent)
    assert ranked[0]["metadata"]["source"].startswith("relation:")


def test_byon_self_description_no_sme_wrong_source():
    intent = qr.classify_intent("descrie acest model BYON")
    ranked = qr.rerank([VAULT_SME, VAULT_FCEM, REPO, RELATION], intent)
    assert not ranked[0]["metadata"]["source"].startswith("vault:")  # no SME/vault as top source
    assert ranked[0]["metadata"]["trust"] == "VERIFIED_PROJECT_FACT"
