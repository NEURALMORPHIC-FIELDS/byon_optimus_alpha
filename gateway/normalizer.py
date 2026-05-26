"""Normalise a BYON verdict into the public response — and enforce the safety gate.

This is where 'no answer without audit' and 'never weaken UNKNOWN' are mechanically
enforced, regardless of what a backend returns:

- If `require_final_audit` and BYON did not pass its final audit, the answer is
  blanked and the status forced to REFUSED. An un-audited answer can never leave.
- A non-KNOWN status always yields `grounded=False` and never carries a confident
  answer body for UNKNOWN/REFUSED/ERROR.
- `epistemic_status` is always one of the five valid labels; anything unexpected
  collapses to ERROR (fail safe, not fail open).
"""
from __future__ import annotations

from .byon_backend import BYONResult
from .types import (
    BYONChatResponse,
    DCortexSummary,
    FCEMSummary,
    GroundingSummary,
    MemorySummary,
)

_VALID = {"KNOWN", "UNKNOWN", "DISPUTED", "REFUSED", "ERROR"}


def normalize(result: BYONResult, *, audit_trace_id: str, user_namespace: str,
              require_final_audit: bool) -> BYONChatResponse:
    status = result.epistemic_status if result.epistemic_status in _VALID else "ERROR"
    answer = result.answer or ""

    # Gate 1 — no answer reaches the user unless BYON's final audit passed.
    if require_final_audit and not result.final_audit_passed:
        if status not in ("UNKNOWN", "DISPUTED", "ERROR"):
            status = "REFUSED"
        answer = ""

    # Gate 2 — only KNOWN may carry a confident answer body; everything else is
    # surfaced as a status, never as an asserted fact.
    grounded = bool(result.grounded) and status == "KNOWN"
    if status != "KNOWN":
        answer = answer if status in ("DISPUTED", "REFUSED") else ""
        grounded = False

    dcortex = (DCortexSummary(**{k: result.dcortex.get(k) for k in
                                 ("verdict", "unknown_gate", "contradiction_status")})
               if result.dcortex else None)
    fcem = None
    if result.fcem:
        fcem = FCEMSummary(
            runtime_proven=bool(result.fcem.get("runtime_proven", False)),
            advisory_nonempty=bool(result.fcem.get("advisory_nonempty", False)),
            pressure_max=result.fcem.get("pressure_max"),
        )

    return BYONChatResponse(
        answer=answer,
        epistemic_status=status,
        grounded=grounded,
        audit_trace_id=audit_trace_id,
        grounding_summary=GroundingSummary(
            has_valid_memory=bool(result.has_valid_memory),
            sources=list(result.sources or []),
            provenance_required=bool(result.provenance_required),
        ),
        memory_summary=MemorySummary(
            user_namespace=user_namespace,
            memory_written=bool(result.memory_written),
            memory_keys=result.memory_keys,
        ),
        dcortex_summary=dcortex,
        fcem_summary=fcem,
    )
