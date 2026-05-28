# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""BYON evidence-acquisition package (Cycle 13.2).

Additive extension of the existing epistemic loop (gateway.epistemic_search): a uniform
EvidencePacket and a set of source adapters (project files, corpus, external-LLM advisory,
budget request) that the loop escalates through when retrieved memory is insufficient. This is
NOT a parallel engine: BYON remains the single epistemic authority; adapters only supply
evidence, and the existing synthesis/verdict logic still decides.
"""
from __future__ import annotations

__all__ = ["evidence_packet", "acquisition"]
