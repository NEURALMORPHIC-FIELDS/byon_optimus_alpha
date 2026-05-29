# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Project-files acquisition adapter (Cycle 13.2).

For a PROJECT/self question that memory could not ground, read the ALPHA repo's own files live
and return the passages that match, as EvidencePackets. Read-only. Respects .gitignore (it reads
only git-tracked files when git is available) and NEVER reads secrets/ or .env* (defence in depth
on top of .gitignore). Project files are authoritative project sources, so a matching passage is
memory-write eligible at VERIFIED_PROJECT_FACT, exactly like the existing self-training corpus.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from gateway import source_policy as sp
from gateway.acquisition.evidence_packet import (EvidencePacket, PacketContent, PacketMemoryWrite,
                                                  PacketSource, PacketTrust)
from gateway.self_training import md_heading_chunks

_TEXT_SUFFIXES = (".md", ".txt", ".py", ".toml", ".cff", ".rst")
_FORBIDDEN = re.compile(r"(?i)(^|/)(secrets?|\.env)(/|$|\.)")
_WORD = re.compile(r"[a-zA-Z0-9_]+")


def _is_forbidden(rel: str) -> bool:
    r = rel.replace("\\", "/")
    return bool(_FORBIDDEN.search(r)) or r.startswith(".env") or "/secrets/" in r or r == ".env"


def _tracked_files(root: Path) -> List[str]:
    """git-tracked files (so .gitignore and secrets/ exclusion are honoured); empty if no git."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=str(root), stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=15)
        return out.stdout.decode("utf-8", errors="ignore").splitlines()
    except (OSError, subprocess.SubprocessError):
        return []


def _keywords(question: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(question or "") if len(w) > 2]


class ProjectFilesAdapter:
    name = "project_files"

    def acquire(self, question: str, context: Dict[str, Any]) -> List[EvidencePacket]:
        # Require an EXPLICIT repo root (acquisition_context or BYON_REPO_ROOT). No cwd ('.')
        # fallback: a caller that does not thread repo_root must not silently scan the process cwd.
        # This makes the Cycle 15 acquisition_context wiring load-bearing (the confirmed asterisk).
        root_str = (context.get("repo_root") or os.environ.get("BYON_REPO_ROOT") or "").strip()
        if not root_str:
            return []
        root = Path(root_str)
        if not root.is_dir():
            return []
        kws = _keywords(question)
        if not kws:
            return []
        files = _tracked_files(root)
        if not files:                                   # no git: fall back to docs + key sources
            files = [str(p.relative_to(root)) for p in root.rglob("*")
                     if p.is_file() and p.suffix in _TEXT_SUFFIXES][:400]
        scored: List[Any] = []
        for rel in files:
            if _is_forbidden(rel):
                continue
            if not rel.lower().endswith(_TEXT_SUFFIXES):
                continue
            fpath = root / rel
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for heading, chunk in md_heading_chunks(text, max_chars=900):
                low = chunk.lower()
                hits = sum(1 for k in set(kws) if k in low)
                if hits >= max(1, len(set(kws)) // 3):
                    scored.append((hits, rel, heading, chunk))
        scored.sort(key=lambda x: -x[0])
        packets: List[EvidencePacket] = []
        for hits, rel, heading, chunk in scored[: int(context.get("max_project_packets", 5))]:
            passage = chunk.strip()[:900]
            packets.append(EvidencePacket(
                source=PacketSource(type="project_file", id=f"repo:{rel}#{heading}",
                                    title=heading, file_path=rel),
                content=PacketContent(raw_text=passage, extracted_claims=[passage],
                                      relevant_passages=[passage],
                                      uncertainty_notes="live repo read; verify against current code"),
                trust=PacketTrust(authority=sp.VERIFIED_PROJECT_FACT,
                                  confidence=min(0.9, 0.5 + 0.1 * hits), freshness=1.0,
                                  provenance_complete=True),
                memory_write=PacketMemoryWrite(eligible=True,
                                               reason="authoritative project source matched the question",
                                               suggested_tier=sp.VERIFIED_PROJECT_FACT)))
        return packets
