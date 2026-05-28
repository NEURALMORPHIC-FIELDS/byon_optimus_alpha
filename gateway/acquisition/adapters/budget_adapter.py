# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Budget-request acquisition adapter (Cycle 13.2).

When no FREE source could ground the answer and the only remaining path is a PAID source, BYON
does not hallucinate. It emits a BudgetRequest (reason, source_needed, expected_gain,
estimated_cost, free_alternatives, post_acquisition_memory_plan) and the loop yields epistemic
status BUDGET_REQUIRED, an explicit, auditable ask, never a fabricated answer.

This is opt-in: it triggers ONLY when the policy/caller signals that free alternatives are
exhausted and a paid source is required (context['paid_source_required'] is True, or the loaded
policy rule paid_source_requires_budget_request is enabled and free sources were exhausted). With
no such signal it returns nothing, so normal queries that legitimately end UNKNOWN are unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from gateway.acquisition.evidence_packet import (INTERNAL_PRESSURE_TRACE, EvidencePacket,
                                                  PacketContent, PacketMemoryWrite, PacketSource,
                                                  PacketTrust)


@dataclass
class BudgetRequest:
    reason: str
    source_needed: str
    expected_gain: str
    estimated_cost: str
    free_alternatives: List[str] = field(default_factory=list)
    post_acquisition_memory_plan: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BudgetAdapter:
    name = "budget"

    def _triggered(self, context: Dict[str, Any]) -> bool:
        # Opt-in only: BYON cannot request a budget for a paid source it does not know exists.
        # An explicit caller/policy signal that a paid source IS available and required is needed;
        # mere exhaustion of free sources stays an honest UNKNOWN, not a budget request.
        if context.get("paid_source_required"):
            return True
        policy = context.get("policy") or {}
        rules = policy.get("rules") or {}
        return bool(rules.get("paid_source_requires_budget_request")
                    and context.get("paid_source_available")
                    and context.get("free_sources_exhausted"))

    def build_request(self, question: str, context: Dict[str, Any]) -> BudgetRequest:
        return BudgetRequest(
            reason=("No free source (memory, project files, model prior, external-LLM advisory, "
                    "web, corpus) could ground this question."),
            source_needed=str(context.get("paid_source_needed")
                              or "a paid/licensed data source (e.g. a paywalled database or API)"),
            expected_gain="a verifiable, citable answer instead of an unsupported guess",
            estimated_cost=str(context.get("paid_source_cost") or "unknown until the source is named"),
            free_alternatives=list(context.get("free_alternatives")
                                   or ["broaden the web query", "ask the user for a source document",
                                       "ingest a relevant corpus the user already owns"]),
            post_acquisition_memory_plan=("On acquisition, store the grounded answer as a candidate "
                                          "with full provenance; promote only after the normal "
                                          "evidence/consolidation path, never as canonical."))

    def acquire(self, question: str, context: Dict[str, Any]) -> List[EvidencePacket]:
        if not self._triggered(context):
            return []
        req = self.build_request(question, context)
        return [EvidencePacket(
            source=PacketSource(type="budget", id="budget:request",
                                title="paid-source budget request"),
            content=PacketContent(raw_text=req.reason, extracted_claims=[],
                                  uncertainty_notes="awaiting owner decision on a paid source"),
            trust=PacketTrust(authority=INTERNAL_PRESSURE_TRACE, confidence=0.0, freshness=1.0,
                              provenance_complete=True),
            memory_write=PacketMemoryWrite(eligible=False,
                                           reason="a budget request is not evidence and is never stored "
                                                  "as a fact"))]
