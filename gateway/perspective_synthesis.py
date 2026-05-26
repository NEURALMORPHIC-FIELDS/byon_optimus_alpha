"""Multi-perspective synthesis → epistemic verdict.

Combines five views (memory / Claude / web / conflict / epistemic) into a single decision.
The rules encode BYON's discipline: committed grounded memory is KNOWN; web-converged
evidence is PROVISIONAL (candidate, not auto-truth) unless policy promotes it; conflicting
web sources are DISPUTED; a Claude-only hypothesis is PROVISIONAL_UNVERIFIED, never KNOWN;
nothing honest left is UNKNOWN (with the searched sources listed).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# committed trust tiers from the canonical memory-service. USER_PREFERENCE counts as
# committed-for-that-user: a fact the user themselves stated, with user provenance.
_COMMITTED_TRUST = {"VERIFIED_PROJECT_FACT", "DOMAIN_VERIFIED", "USER_PREFERENCE"}

STATUSES = ("KNOWN", "PROVISIONAL", "PROVISIONAL_UNVERIFIED", "DISPUTED",
            "NEEDS_MORE_TIME", "ASK_USER_FOR_SOURCE", "UNKNOWN", "REFUSED", "ERROR")


def _hit_text(h: Dict[str, Any]) -> str:
    return h.get("content") or h.get("text") or h.get("fact") or ""


def _hit_trust(h: Dict[str, Any]) -> Optional[str]:
    md = h.get("metadata") or {}
    return h.get("trust") or md.get("trust")


def _web_claims(web_results: List[Any], hypothesis_value: Optional[str]) -> Dict[str, int]:
    """Count distinct claims supported across web results."""
    counts: Dict[str, int] = {}
    for r in web_results:
        claim = getattr(r, "claim", None)
        snippet = (getattr(r, "snippet", "") or "")
        if not claim and hypothesis_value and hypothesis_value.lower() in snippet.lower():
            claim = hypothesis_value
        if claim:
            counts[claim] = counts.get(claim, 0) + 1
    return counts


def synthesize(*, question: str, memory_hits: List[Dict[str, Any]],
               candidate_hits: List[Dict[str, Any]], claude_hypothesis: Optional[Dict[str, Any]],
               web_results: List[Any], web_enabled: bool, auto_commit_web: bool = False,
               min_web_sources: int = 2) -> Dict[str, Any]:
    hypo_val = (claude_hypothesis or {}).get("hypothesis") if claude_hypothesis else None

    # --- the five views -----------------------------------------------------
    committed = [h for h in memory_hits if (_hit_trust(h) in _COMMITTED_TRUST)]
    grounded_hit = committed[0] if committed else (memory_hits[0] if memory_hits else None)
    memory_view = (_hit_text(grounded_hit) if grounded_hit else "no committed memory for this")
    claude_view = (f"hypothesis: {hypo_val} (requires verification)" if hypo_val
                   else ("not consulted" if claude_hypothesis is None else "no hypothesis"))
    claim_counts = _web_claims(web_results, hypo_val)
    distinct_claims = sorted(claim_counts, key=lambda c: -claim_counts[c])
    if not web_enabled:
        web_view = "web search disabled"
    elif not web_results:
        web_view = "web searched, no usable evidence"
    else:
        web_view = "; ".join(f"{c} (x{claim_counts[c]})" for c in distinct_claims) or \
                   f"{len(web_results)} results, no extracted claim"
    conflicting = len(distinct_claims) >= 2
    conflict_view = ("web sources disagree: " + " vs ".join(distinct_claims)) if conflicting \
        else ("no conflict detected" if not (memory_hits and hypo_val and
              hypo_val.lower() not in memory_view.lower()) else "memory vs hypothesis differ")

    # --- decision -----------------------------------------------------------
    answer, status, confidence, sources = "", "UNKNOWN", 0.0, []
    candidate: Optional[Dict[str, Any]] = None

    if grounded_hit and _hit_trust(grounded_hit) in _COMMITTED_TRUST:
        answer = _hit_text(grounded_hit)
        status, confidence = "KNOWN", 0.9
        sources = [(grounded_hit.get("metadata") or {}).get("source") or grounded_hit.get("source") or "memory:committed"]
    elif conflicting:
        answer = f"Sources disagree: {', '.join(distinct_claims)}."
        status, confidence = "DISPUTED", 0.4
        sources = [getattr(r, "url", "") for r in web_results if getattr(r, "url", "")]
    elif distinct_claims:  # single converged web claim
        top = distinct_claims[0]
        supporting = claim_counts[top]
        answer = top
        sources = [getattr(r, "url", "") for r in web_results if getattr(r, "url", "")]
        if auto_commit_web and supporting >= min_web_sources:
            status, confidence = "KNOWN", 0.85
        else:
            status, confidence = "PROVISIONAL", 0.65
        candidate = {"value": top, "source_type": "web", "sources": sources,
                     "evidence_count": supporting}
    elif grounded_hit:  # uncommitted memory candidate
        answer = _hit_text(grounded_hit)
        status, confidence = "PROVISIONAL", 0.55
        sources = [(grounded_hit.get("metadata") or {}).get("source") or "memory:candidate"]
    elif hypo_val:  # Claude prior only — never KNOWN
        answer = (f"Claude's unverified hypothesis is: {hypo_val}. I cannot mark it KNOWN "
                  f"without source confirmation"
                  + (" (web search is disabled)." if not web_enabled else "."))
        status, confidence = "PROVISIONAL_UNVERIFIED", 0.35
    else:
        if not web_enabled:
            answer = "I don't have this in memory and web search is disabled."
            status = "ASK_USER_FOR_SOURCE"
        else:
            answer = ""
            status = "UNKNOWN"
        confidence = 0.0

    return {
        "memory_view": memory_view,
        "claude_view": claude_view,
        "web_view": web_view,
        "conflict_view": conflict_view,
        "epistemic_verdict": status,
        "confidence": confidence,
        "answer": answer,
        "sources": [s for s in sources if s],
        "candidate": candidate,
        "distinct_claims": distinct_claims,
    }
