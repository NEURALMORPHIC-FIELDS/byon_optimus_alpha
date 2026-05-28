# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Semantic evidence classifier (Cycle 9, target 1).

Decides how two claims relate - same / supports / contradicts / unrelated / narrows / broadens /
canonical_conflict - so the candidate lifecycle merges paraphrases, disputes real contradictions,
and keeps unrelated claims separate. It is NOT a truth oracle:

  * deterministic rules (canonical constraints, exact/lexical match, negation & antonym polarity)
    are primary and testable;
  * a Claude/NLI pass is ADVISORY only (opt-in BYON_EVIDENCE_NLI) - it may suggest a relation but
    never overrides the source policy and never decides truth;
  * a SYSTEM_CANONICAL conflict always dominates the semantic similarity;
  * secret content is never classified into candidate memory.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from gateway.source_policy import CANONICAL_CONSTRAINTS

# relations
SAME = "same_claim"
SUPPORTS = "supports"
CONTRADICTS = "contradicts"
UNRELATED = "unrelated"
NARROWS = "narrows"
BROADENS = "broadens"
CANONICAL_CONFLICT = "canonical_conflict"

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "is", "are", "be", "of", "to", "in", "on", "and", "or", "for", "that",
         "this", "it", "its", "as", "at", "by", "with", "my", "your",
         "este", "e", "un", "o", "si", "și", "la", "in", "în", "de", "ce", "are", "mea", "meu"}
_NEG = {"not", "no", "never", "cannot", "cant", "n't", "without", "nu", "fara", "fără", "non", "niciodata"}
_ANTONYMS = [
    {"up", "down"}, {"true", "false"}, {"won", "lost"}, {"yes", "no"}, {"can", "cannot"},
    {"allowed", "forbidden"}, {"advisory", "authority"}, {"open", "closed"}, {"hot", "cold"},
    {"level2", "level3"}, {"level 2", "level 3"},
]
_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
             "luni", "marti", "miercuri", "joi", "vineri", "sambata", "duminica"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower()).rstrip(".!? ")


def _tokens(s: str) -> set:
    return {t for t in _TOKEN.findall((s or "").lower()) if t not in _STOP}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _has_neg(tokens: set, raw: str) -> bool:
    low = " " + (raw or "").lower() + " "
    return bool(tokens & _NEG) or "n't" in low or " not " in low or " nu " in low


def _antonym_conflict(ta: set, tb: set) -> bool:
    for pair in _ANTONYMS:
        if (ta & pair) and (tb & pair) and (ta & pair) != (tb & pair):
            return True
    return False


def _value_conflict(ta: set, tb: set, shared: set) -> bool:
    """Same subject (shared tokens) but each side carries a DIFFERENT distinctive value
    (e.g. weekday/number/proper-token) -> different answer to the same question."""
    if not shared:
        return False
    da, db = ta - tb, tb - ta
    va = {t for t in da if t in _WEEKDAYS or t.isdigit()}
    vb = {t for t in db if t in _WEEKDAYS or t.isdigit()}
    return bool(va and vb and va != vb)


def _canonical_conflict(a: str, b: str) -> Optional[Dict[str, Any]]:
    """Two claims about the same fixed canonical constraint where exactly one asserts the
    forbidden thing (e.g. 'BYON is Level 3' vs 'BYON is Level 2')."""
    for c in CANONICAL_CONSTRAINTS:
        if c["topic"].search(a) and c["topic"].search(b):
            ua, ub = bool(c["unsafe"].search(a)), bool(c["unsafe"].search(b))
            if ua != ub:
                return {"constraint": c["name"], "truth": c["truth"]}
    return None


def classify_evidence_relation(claim_a: str, claim_b: str, *, context: Optional[Dict[str, Any]] = None,
                               sources: Optional[List[str]] = None,
                               claude_advisor: Optional[Any] = None) -> Dict[str, Any]:
    ctx = context or {}
    if ctx.get("is_secret"):
        return {"relation": UNRELATED, "confidence": 0.0, "reason": "secret content not classified",
                "method": "secret_guard"}

    # 1) deterministic canonical override - always dominates
    cc = _canonical_conflict(claim_a, claim_b)
    if cc or "SYSTEM_CANONICAL" in (ctx.get("source_class_a"), ctx.get("source_class_b")) and \
            _polarity_conflict(claim_a, claim_b):
        return {"relation": CANONICAL_CONFLICT, "confidence": 0.99,
                "reason": (cc or {}).get("truth", "conflicts with a canonical fact"),
                "method": "deterministic_canonical"}

    na, nb = _norm(claim_a), _norm(claim_b)
    if na == nb:
        return {"relation": SAME, "confidence": 1.0, "reason": "identical normalized claim",
                "method": "deterministic_exact"}

    ta, tb = _tokens(claim_a), _tokens(claim_b)
    jac = _jaccard(ta, tb)
    shared = ta & tb

    # 2) polarity / value contradiction (paraphrased contradiction)
    if _polarity_conflict(claim_a, claim_b) and jac >= 0.3:
        return {"relation": CONTRADICTS, "confidence": round(0.6 + 0.3 * jac, 3),
                "reason": "shared subject with opposite polarity / different value",
                "method": "deterministic_polarity"}

    # 3) lexical-embedding similarity for same / support
    if jac >= 0.82:
        return {"relation": SAME, "confidence": round(jac, 3), "reason": "paraphrase (high overlap)",
                "method": "lexical_similarity"}
    if ta and tb and ta < tb:
        return {"relation": NARROWS, "confidence": round(len(shared) / max(1, len(ta)), 3),
                "reason": "b is a more specific version of a", "method": "lexical_subset"}
    if ta and tb and tb < ta:
        return {"relation": BROADENS, "confidence": round(len(shared) / max(1, len(tb)), 3),
                "reason": "b is a more general version of a", "method": "lexical_subset"}
    if jac >= 0.5:
        return {"relation": SUPPORTS, "confidence": round(jac, 3),
                "reason": "corroborating claim, same polarity", "method": "lexical_similarity"}
    if jac < 0.25:
        # optional advisory NLI only as a tie-breaker for the low-overlap zone - never authority
        adv = _claude_advice(claim_a, claim_b, claude_advisor)
        if adv:
            return adv
        return {"relation": UNRELATED, "confidence": round(1 - jac, 3), "reason": "low overlap",
                "method": "lexical_similarity"}
    adv = _claude_advice(claim_a, claim_b, claude_advisor)
    return adv or {"relation": UNRELATED, "confidence": 0.5,
                   "reason": "moderate overlap, no clear relation", "method": "lexical_similarity"}


def _polarity_conflict(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    neg_a, neg_b = _has_neg(ta, a), _has_neg(tb, b)
    if neg_a != neg_b and _jaccard(ta, tb) >= 0.3:
        return True
    if _antonym_conflict(ta, tb):
        return True
    if _value_conflict(ta, tb, ta & tb):
        return True
    return False


def _claude_advice(a: str, b: str, advisor: Any) -> Any:
    """Advisory NLI via Claude - opt-in, suggestion only, never authority/truth."""
    if advisor is None or os.environ.get("BYON_EVIDENCE_NLI", "false").strip().lower() not in (
            "1", "true", "yes", "on"):
        return None
    try:
        rel = advisor(a, b)   # advisor returns one of the relation strings or None
        if rel in (SAME, SUPPORTS, CONTRADICTS, UNRELATED, NARROWS, BROADENS):
            return {"relation": rel, "confidence": 0.55, "reason": "Claude NLI advisory (not authority)",
                    "method": "claude_advisory"}
    except Exception:
        return None
    return None
