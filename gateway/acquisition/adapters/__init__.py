# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Source adapters for BYON evidence acquisition (Cycle 13.2).

Each adapter exposes `acquire(question, context) -> list[EvidencePacket]` and only emits packets
under its own activation condition, so it never perturbs a query it does not apply to. No agents,
personas, or councils: these are source adapters only.
"""
from __future__ import annotations

from gateway.acquisition.adapters.budget_adapter import BudgetAdapter, BudgetRequest
from gateway.acquisition.adapters.corpus_adapter import CorpusAdapter
from gateway.acquisition.adapters.external_llm_adapter import ExternalLLMAdapter
from gateway.acquisition.adapters.project_files_adapter import ProjectFilesAdapter

__all__ = ["ProjectFilesAdapter", "CorpusAdapter", "ExternalLLMAdapter", "BudgetAdapter",
           "BudgetRequest"]
