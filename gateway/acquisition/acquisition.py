# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Acquisition orchestrator (Cycle 13.2): the sufficiency gate + tiered source escalation.

This is the glue the existing epistemic loop calls when retrieved memory is insufficient. It does
NOT decide verdicts and it does NOT replace any engine: it asks the source adapters (in policy
order) for EvidencePackets, then folds them into the inputs the EXISTING synthesis already
understands (grounding hits and candidate claims). BYON's synthesis/verdict logic is unchanged.

Sufficiency is computed only from the hits already retrieved (coverage of question keywords,
freshness of the top hit, and the missing slots), compared to a complexity-based threshold from
acquisition_policy.json. If the policy file is absent, DEFAULT_POLICY is used and the loop's prior
behavior is preserved.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from gateway import query_router as qr
from gateway import source_policy as sp
from gateway.acquisition.adapters import (BudgetAdapter, CorpusAdapter, ExternalLLMAdapter,
                                          ProjectFilesAdapter)
from gateway.acquisition.evidence_packet import EvidencePacket

DEFAULT_POLICY: Dict[str, Any] = {
    "version": "13.2-default",
    "sufficiency_thresholds": {"simple": 0.55, "medium": 0.70, "complex": 0.82, "high_stakes": 0.90},
    "source_order": ["local_memory", "project_files", "model_prior", "external_llm", "web",
                     "corpus", "budget", "user_clarification"],
    "rules": {
        "empty_memory_triggers_acquisition": True,
        "project_questions_require_repo_files": True,
        "current_info_requires_web": True,
        "book_questions_require_corpus_ingestion": True,
        "paid_source_requires_budget_request": True,
        "model_prior_never_becomes_verified_fact_without_external_support": True,
        "external_llm_output_is_advisory_only": True,
        "all_new_memory_requires_provenance": True,
    },
}

# tier name -> adapter class (the adapters this orchestrator can run)
_ADAPTERS = {
    "project_files": ProjectFilesAdapter,
    "external_llm": ExternalLLMAdapter,
    "corpus": CorpusAdapter,
    "budget": BudgetAdapter,
}
# authorities that genuinely ground (a packet at these tiers may answer); others are advisory.
_GROUND_AUTHORITIES = frozenset({sp.SYSTEM_CANONICAL, sp.VERIFIED_PROJECT_FACT, sp.DOMAIN_VERIFIED})
_WORD = re.compile(r"[a-zA-Z0-9_]+")
_HIGH_STAKES = re.compile(r"(?i)\b(medical|legal|diagnos|dosage|safety|financial|invest|patent|"
                          r"security|password|legaliz|lege|medic|juridic|doz)\b")


def load_policy(base_dir: Optional[str] = None) -> Dict[str, Any]:
    """Load acquisition_policy.json next to this package; fall back to DEFAULT_POLICY if missing."""
    path = Path(base_dir) if base_dir else Path(__file__).resolve().parent / "acquisition_policy.json"
    if path.is_dir():
        path = path / "acquisition_policy.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_POLICY


def complexity_of(question: str, intent: str, qclass: str) -> str:
    q = question or ""
    if _HIGH_STAKES.search(q):
        return "high_stakes"
    words = len(_WORD.findall(q))
    if intent in (qr.SELF_ARCHITECTURE_QUERY, qr.CONTRADICTION_QUERY, qr.RELATION_FIELD_QUERY):
        return "complex"
    if words >= 16 or "?" in q[:-1]:
        return "complex"
    if words >= 7:
        return "medium"
    return "simple"


def _keywords(question: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(question or "") if len(w) > 2]


def assess_sufficiency(*, question: str, memory_hits: List[Dict[str, Any]],
                       committed: List[Dict[str, Any]], intent: str, qclass: str,
                       policy: Dict[str, Any]) -> Dict[str, Any]:
    """Sufficiency in [0,1] from the ALREADY-retrieved hits: coverage of question keywords by the
    committed hits, freshness of the top hit, minus the fraction of missing slots. Compared to the
    complexity threshold. A committed hit covering the keywords is sufficient; empty memory is not."""
    kws = set(_keywords(question))
    comp = complexity_of(question, intent, qclass)
    threshold = float(policy.get("sufficiency_thresholds", {}).get(
        comp, DEFAULT_POLICY["sufficiency_thresholds"][comp]))
    grounding = committed or memory_hits
    covered: set = set()
    for h in grounding:
        text = (h.get("content") or h.get("text") or h.get("fact") or "").lower()
        covered |= {k for k in kws if k in text}
    coverage = (len(covered) / len(kws)) if kws else (1.0 if grounding else 0.0)
    try:
        top_sim = float(grounding[0].get("similarity", grounding[0].get("score"))) if grounding else 0.0
    except (TypeError, ValueError, IndexError):
        top_sim = 0.0
    freshness = 1.0 if committed else (0.5 if memory_hits else 0.0)
    missing_slots = sorted(kws - covered)
    score = round(max(0.0, 0.6 * coverage + 0.3 * freshness + 0.1 * min(1.0, top_sim)), 3)
    sufficient = bool(committed) and score >= threshold and not missing_slots
    return {"sufficient": sufficient, "score": score, "threshold": threshold, "complexity": comp,
            "coverage": round(coverage, 3), "freshness": freshness, "missing_slots": missing_slots}


def run_tiers(question: str, context: Dict[str, Any], tiers: List[str]) -> Dict[str, Any]:
    """Run the named adapter tiers in order; collect packets. Each adapter only emits under its own
    activation condition, so a tier that does not apply contributes nothing."""
    packets: List[EvidencePacket] = []
    tiers_run: List[str] = []
    budget_request = None
    for tier in tiers:
        cls = _ADAPTERS.get(tier)
        if cls is None:
            continue
        adapter = cls()
        produced = adapter.acquire(question, context) or []
        tiers_run.append(tier)
        packets.extend(produced)
        if tier == "budget" and produced:
            budget_request = adapter.build_request(question, context).to_dict()
    return {"packets": packets, "tiers_run": tiers_run, "budget_request": budget_request}


def _claim_key(packet: EvidencePacket) -> str:
    raw = packet.primary_claim().lower()
    return " ".join(_WORD.findall(raw))[:80]


def fold_packets(packets: List[EvidencePacket]) -> Dict[str, Any]:
    """Fold acquired packets into synthesis inputs WITHOUT deciding the verdict.

    Returns: ground_top (best grounding packet or None), advisory_web_results (advisory/web-grade
    packets as web-result-like dicts), conflict (>=2 distinct candidate claims), and the distinct
    candidate claim keys. Advisory authorities (external-LLM / model-prior / pressure) are never
    promoted to grounding."""
    # a budget request is not evidence; it never grounds and is never a candidate claim.
    evidence = [p for p in packets if p.source.type != "budget"]
    ground = [p for p in evidence if (not p.is_advisory_only())
              and p.trust.authority in _GROUND_AUTHORITIES and p.memory_write.eligible]
    advisory = [p for p in evidence if p.is_advisory_only()
                or (p.trust.authority == sp.PROVISIONAL_WEB)]
    ground.sort(key=lambda p: p.trust.confidence, reverse=True)
    ground_top = ground[0] if ground else None
    candidate_keys: List[str] = []
    if ground_top:
        candidate_keys.append(_claim_key(ground_top))
    advisory_results: List[Dict[str, Any]] = []
    for p in advisory:
        key = _claim_key(p)
        if key:
            candidate_keys.append(key)
        advisory_results.append({"title": p.source.title, "url": p.source.url or p.source.id,
                                 "snippet": p.content.raw_text, "source_domain": p.source.type,
                                 "claim": p.primary_claim()[:160]})
    distinct = sorted(set(k for k in candidate_keys if k))
    return {"ground_top": ground_top, "advisory_results": advisory_results,
            "conflict": len(distinct) >= 2, "distinct_claims": distinct,
            "ground_count": len(ground), "advisory_count": len(advisory)}


def ground_packet_as_hit(packet: EvidencePacket) -> Dict[str, Any]:
    """Represent a grounding packet as a memory-service-style hit so the EXISTING synthesis can
    treat it as committed grounding (with its provenance and suggested tier)."""
    tier = packet.memory_write.suggested_tier or packet.trust.authority
    return {"content": packet.content.raw_text, "score": packet.trust.confidence,
            "similarity": packet.trust.confidence,
            "metadata": {"trust": tier, "source": packet.source.id or packet.source.file_path,
                         "acquired": True}}
