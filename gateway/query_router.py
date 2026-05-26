"""Query intent router + trust-tier retrieval re-ranking.

Fixes ranking: a memory hit's final rank is its semantic similarity PLUS a trust-tier boost
PLUS an intent boost, so a canonical VERIFIED_PROJECT_FACT / relation fact can no longer be
out-ranked by a higher-cosine vault EXTRACTED_USER_CLAIM for an architecture question — while
vault notes still dominate for "what did I write…" questions.

Trust order (high→low):
  SYSTEM_CANONICAL > VERIFIED_PROJECT_FACT > DOMAIN_VERIFIED > USER_PREFERENCE >
  EXTRACTED_USER_CLAIM > PROVISIONAL_WEB > DISPUTED_OR_UNSAFE
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

TRUST_RANK = {
    "SYSTEM_CANONICAL": 6, "VERIFIED_PROJECT_FACT": 5, "DOMAIN_VERIFIED": 4,
    "USER_PREFERENCE": 3, "EXTRACTED_USER_CLAIM": 2, "PROVISIONAL_WEB": 1,
    None: 1, "": 1, "DISPUTED_OR_UNSAFE": 0,
}
COMMITTED_TIERS = {"SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT", "DOMAIN_VERIFIED", "USER_PREFERENCE"}

SELF_TERMS = ["byon", "d_cortex", "d-cortex", "dcortex", "fce-m", "fcem", "auditor",
              "memory-service", "memory service", "orchestrator", "worker", "executor",
              "claude role", "level 2", "level 3", "epistemic contract", "level3", "level2"]
VAULT_TRIGGERS = ["ce am scris", "ce-am scris", "in notele mele", "în notele mele", "notele mele",
                  "unde am mentionat", "unde am menționat", "rezuma vault", "rezumă vault",
                  "vault-ul meu", "vault meu", "my notes", "what did i write", "in my vault",
                  "din notele"]
CONTRADICTION_TRIGGERS = ["contradic", "conflicting", "in conflict", "în conflict", "disput",
                          "gresit", "greșit", "wrong fact", "contradiction"]
_SECRET = re.compile(r"(?i)\b(password|secret|private key|api[ _-]?key|token|pin|ssn|credit\s*card)\b")

SELF_ARCHITECTURE_QUERY = "SELF_ARCHITECTURE_QUERY"
USER_VAULT_QUERY = "USER_VAULT_QUERY"
GENERAL_FACT_QUERY = "GENERAL_FACT_QUERY"
SECRET_QUERY = "SECRET_QUERY"
CONTRADICTION_QUERY = "CONTRADICTION_QUERY"


def classify_intent(question: str) -> str:
    q = (question or "").lower()
    if _SECRET.search(q):
        return SECRET_QUERY
    if any(t in q for t in VAULT_TRIGGERS):
        return USER_VAULT_QUERY
    if any(t in q for t in CONTRADICTION_TRIGGERS):
        return CONTRADICTION_QUERY
    if any(t in q for t in SELF_TERMS):
        return SELF_ARCHITECTURE_QUERY
    return GENERAL_FACT_QUERY


def _src(h: Dict[str, Any]) -> str:
    return ((h.get("metadata") or {}).get("source") or h.get("source") or "")


def _trust(h: Dict[str, Any]) -> str:
    return (h.get("metadata") or {}).get("trust") or h.get("trust")


def _sim(h: Dict[str, Any]) -> float:
    v = h.get("similarity", h.get("score"))
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def rerank(hits: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
    """Return hits sorted by combined score (similarity + trust boost + intent boost)."""
    scored = []
    for h in hits:
        src = _src(h)
        tier = TRUST_RANK.get(_trust(h), 1)
        base = _sim(h)
        boost = 0.0
        if intent in (SELF_ARCHITECTURE_QUERY, CONTRADICTION_QUERY):
            boost += 0.18 * tier                       # strongly prefer trusted tiers
            if src.startswith("relation:"):
                boost += 1.0                           # canonical relations first
            elif src.startswith("repo:"):
                boost += 0.6                           # repo/docs next
            elif src.startswith("vault:"):
                boost -= 0.6                            # vault is lower priority here
        elif intent == USER_VAULT_QUERY:
            if src.startswith("vault:"):
                boost += 0.8                            # vault dominates
            elif src.startswith(("relation:", "repo:")):
                boost -= 0.4
            boost += 0.04 * tier
        else:  # GENERAL_FACT_QUERY
            boost += 0.10 * tier
        h = dict(h)
        h["_combined"] = base + boost
        h["_tier"] = tier
        scored.append(h)
    scored.sort(key=lambda x: x["_combined"], reverse=True)
    return scored


def committed(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [h for h in hits if _trust(h) in COMMITTED_TIERS]
