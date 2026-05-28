# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""EvidencePacket: the uniform unit every acquisition source emits (Cycle 13.2).

A packet is EVIDENCE, never a verdict. It records WHERE the evidence came from (source),
WHAT it says (content), HOW far it can be trusted (trust), and WHETHER it may be written to
memory and at which tier (memory_write). The epistemic loop and synthesis still decide the
verdict; a packet only carries the material they decide over, with full provenance.

Authority vocabulary (high to low for acquired evidence; canonical/project memory facts always
outrank these): EXTERNAL_VERIFIED > MODEL_PRIOR_UNVERIFIED > EXTERNAL_LLM_ADVISORY >
INTERNAL_PRESSURE_TRACE. An EXTERNAL_LLM_ADVISORY or MODEL_PRIOR_UNVERIFIED packet may never,
on its own, make an answer KNOWN, and is never written to memory as a verified fact.

memory_hit_to_packet() and web_result_to_packet() represent the loop's EXISTING memory hits and
web results as packets WITHOUT changing any verdict: they are pure representations used so the
loop can reason over one uniform evidence type.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from gateway import source_policy as sp

# Authorities specific to acquired (non-memory) evidence.
EXTERNAL_VERIFIED = "EXTERNAL_VERIFIED"
MODEL_PRIOR_UNVERIFIED = "MODEL_PRIOR_UNVERIFIED"
EXTERNAL_LLM_ADVISORY = "EXTERNAL_LLM_ADVISORY"
INTERNAL_PRESSURE_TRACE = "INTERNAL_PRESSURE_TRACE"

# Authorities that may NEVER, alone, produce KNOWN or be written as a verified fact.
ADVISORY_ONLY_AUTHORITIES = frozenset({MODEL_PRIOR_UNVERIFIED, EXTERNAL_LLM_ADVISORY,
                                       INTERNAL_PRESSURE_TRACE})


@dataclass
class PacketSource:
    type: str                                   # memory | project_file | corpus | external_llm | web | budget
    id: str = ""
    title: str = ""
    url: str = ""
    file_path: str = ""
    model_id: str = ""
    timestamp: str = ""


@dataclass
class PacketContent:
    raw_text: str = ""
    extracted_claims: List[str] = field(default_factory=list)
    relevant_passages: List[str] = field(default_factory=list)
    uncertainty_notes: str = ""


@dataclass
class PacketTrust:
    authority: str = sp.UNKNOWN                 # a source_policy class or an acquisition authority
    confidence: float = 0.0
    freshness: float = 0.0                      # 0 stale .. 1 fresh
    provenance_complete: bool = False


@dataclass
class PacketMemoryWrite:
    eligible: bool = False
    reason: str = ""
    suggested_tier: Optional[str] = None        # a source_policy trust tier, or None


@dataclass
class EvidencePacket:
    source: PacketSource
    content: PacketContent
    trust: PacketTrust
    memory_write: PacketMemoryWrite
    packet_id: str = field(default_factory=lambda: "ev_" + uuid.uuid4().hex)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def is_advisory_only(self) -> bool:
        """True when this packet may never, alone, make an answer KNOWN."""
        return self.trust.authority in ADVISORY_ONLY_AUTHORITIES

    def primary_claim(self) -> str:
        if self.content.extracted_claims:
            return self.content.extracted_claims[0]
        return (self.content.raw_text or "").strip()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def memory_hit_to_packet(hit: Dict[str, Any]) -> EvidencePacket:
    """Represent an EXISTING memory-service hit as a packet. No verdict change: the hit's own
    trust tier becomes the packet authority, and memory-write is not re-proposed (it is already
    in memory)."""
    md = hit.get("metadata") or {}
    text = hit.get("content") or hit.get("text") or hit.get("fact") or ""
    tier = md.get("trust") or hit.get("trust")
    try:
        conf = float(hit.get("similarity", hit.get("score")))
    except (TypeError, ValueError):
        conf = 0.0
    return EvidencePacket(
        source=PacketSource(type="memory", id=str(md.get("source") or hit.get("source") or ""),
                            title="committed/session memory", timestamp=str(md.get("timestamp") or "")),
        content=PacketContent(raw_text=text, extracted_claims=[text] if text else []),
        trust=PacketTrust(authority=tier or sp.UNKNOWN, confidence=conf, freshness=1.0,
                          provenance_complete=bool(md.get("source"))),
        memory_write=PacketMemoryWrite(eligible=False, reason="already in memory"))


def web_result_to_packet(result: Any) -> EvidencePacket:
    """Represent an EXISTING web result as a packet. Web evidence stays PROVISIONAL_WEB; it is a
    candidate, not auto-truth, exactly as the existing loop already treats it."""
    claim = getattr(result, "claim", None)
    snippet = getattr(result, "snippet", "") or ""
    url = getattr(result, "url", "") or ""
    return EvidencePacket(
        source=PacketSource(type="web", url=url, title=getattr(result, "title", "") or "",
                            id=getattr(result, "source_domain", "") or "",
                            timestamp=getattr(result, "retrieved_at", "") or ""),
        content=PacketContent(raw_text=snippet, relevant_passages=[snippet] if snippet else [],
                              extracted_claims=[claim] if claim else []),
        trust=PacketTrust(authority=sp.PROVISIONAL_WEB, confidence=0.5, freshness=0.8,
                          provenance_complete=bool(url)),
        memory_write=PacketMemoryWrite(eligible=False,
                                       reason="web candidate; promotion needs source convergence"))
