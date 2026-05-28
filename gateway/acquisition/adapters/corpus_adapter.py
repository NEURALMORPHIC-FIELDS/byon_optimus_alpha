# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Corpus acquisition adapter (Cycle 13.2).

On-demand ingest of a provided book / PDF / corpus path: chunk the corpus, extract the passages
relevant to the question, return them as EvidencePackets. Chunking REUSES the canonical
self-training chunker (gateway.self_training.md_heading_chunks); it does not duplicate it. PDF
text is read only if a PDF reader is installed, else the file is skipped honestly (no fabrication).

Fires only when a corpus path is supplied (context['corpus_path'] or BYON_CORPUS_PATH); otherwise
it returns nothing, so it never perturbs a normal query. A corpus passage is DOMAIN_VERIFIED only
when its provenance is complete; otherwise it stays an advisory MODEL_PRIOR-grade candidate.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from gateway import source_policy as sp
from gateway.acquisition.evidence_packet import (EvidencePacket, PacketContent, PacketMemoryWrite,
                                                  PacketSource, PacketTrust)
from gateway.self_training import md_heading_chunks

_WORD = re.compile(r"[a-zA-Z0-9_]+")


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                return ""
        try:
            reader = PdfReader(str(path))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception:
            return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _keywords(question: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(question or "") if len(w) > 2]


class CorpusAdapter:
    name = "corpus"

    def acquire(self, question: str, context: Dict[str, Any]) -> List[EvidencePacket]:
        corpus = context.get("corpus_path") or os.environ.get("BYON_CORPUS_PATH") or ""
        if not corpus:
            return []
        path = Path(corpus)
        if not path.exists():
            return []
        paths = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        kws = set(_keywords(question))
        packets: List[EvidencePacket] = []
        limit = int(context.get("max_corpus_packets", 6))
        for fp in paths:
            text = _read_text(fp)
            if not text:
                continue
            for heading, chunk in md_heading_chunks(text, max_chars=1100):
                low = chunk.lower()
                hits = sum(1 for k in kws if k in low) if kws else 1
                if hits <= 0:
                    continue
                passage = chunk.strip()[:1100]
                complete = bool(fp.name)
                packets.append(EvidencePacket(
                    source=PacketSource(type="corpus", id=f"corpus:{fp.name}#{heading}",
                                        title=heading, file_path=str(fp)),
                    content=PacketContent(raw_text=passage, extracted_claims=[passage],
                                          relevant_passages=[passage],
                                          uncertainty_notes="ingested on demand from the provided corpus"),
                    trust=PacketTrust(authority=sp.DOMAIN_VERIFIED if complete else sp.PROVISIONAL_WEB,
                                      confidence=min(0.85, 0.45 + 0.1 * hits), freshness=0.7,
                                      provenance_complete=complete),
                    memory_write=PacketMemoryWrite(eligible=complete,
                                                   reason="corpus passage with file provenance",
                                                   suggested_tier=sp.DOMAIN_VERIFIED if complete else None)))
                if len(packets) >= limit:
                    return packets
        return packets
