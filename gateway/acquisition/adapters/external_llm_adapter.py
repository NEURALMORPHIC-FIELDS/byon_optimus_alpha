# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""External-LLM advisory acquisition adapter (Cycle 13.2).

Env-gated multi-model advisory: BYON_EXTERNAL_LLMS="openai,gemini,ollama" selects which external
models are consulted. EVERY output is authority EXTERNAL_LLM_ADVISORY and is NEVER, on its own,
KNOWN and NEVER written to memory as a verified fact. This is a second opinion, not a source of
truth; BYON remains the single epistemic authority and web stays the canonical web layer
(gateway.web_search) which this adapter does not rebuild.

Network calls are made only by a caller injected through context['external_model_caller'] (a
fn(model_id, question) -> str). With no caller and no configured backend, the adapter returns
nothing, so it never perturbs a normal query and never invents an answer.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from gateway.acquisition.evidence_packet import (EXTERNAL_LLM_ADVISORY, EvidencePacket,
                                                  PacketContent, PacketMemoryWrite, PacketSource,
                                                  PacketTrust)


def _configured_models() -> List[str]:
    raw = os.environ.get("BYON_EXTERNAL_LLMS", "").strip()
    return [m.strip().lower() for m in raw.split(",") if m.strip()]


class ExternalLLMAdapter:
    name = "external_llm"

    def acquire(self, question: str, context: Dict[str, Any]) -> List[EvidencePacket]:
        caller: Optional[Callable[[str, str], str]] = context.get("external_model_caller")
        models = context.get("external_models") or _configured_models()
        if not models or caller is None:
            return []
        packets: List[EvidencePacket] = []
        for model_id in models:
            try:
                text = (caller(model_id, question) or "").strip()
            except Exception:
                continue
            if not text:
                continue
            packets.append(EvidencePacket(
                source=PacketSource(type="external_llm", id=f"external_llm:{model_id}",
                                    title=f"advisory opinion ({model_id})", model_id=model_id),
                content=PacketContent(raw_text=text, extracted_claims=[text],
                                      uncertainty_notes="external-LLM advisory; not verified, not authority"),
                trust=PacketTrust(authority=EXTERNAL_LLM_ADVISORY, confidence=0.4, freshness=0.6,
                                  provenance_complete=True),
                memory_write=PacketMemoryWrite(eligible=False,
                                               reason="advisory only; never a verified fact without "
                                                      "independent external support")))
        return packets
