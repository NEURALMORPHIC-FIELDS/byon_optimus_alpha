"""Phase 3 — self-training on BYON's own canonical corpus (no presets, no hardcoded answers).

Ingests the repo's docs + key module docstrings through the CANONICAL pipeline:
corpus → heading-aware chunks → memory-service store (FAISS) → trust tier → FCE-M consolidate.
Project docs are authoritative project sources → trust VERIFIED_PROJECT_FACT, system scope
(thread_id=None) so any session can recall BYON's self-knowledge with provenance.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .memory_service_client import MemoryServiceClient

# Default canonical corpus: docs (full) + module docstrings (intent) for the key components.
_DOC_FILES = ["README.md", "STATUS.md", "CHANGELOG.md", "MILESTONE_v10.0.md", "SECURITY.md",
              "docs/ARCHITECTURE.md", "docs/RESEARCH_REPORT.md",
              "external/byon_optimus/CLAUDE.md"]
_CODE_FILES = ["dcortex/v99_source.py", "dcortex/v10_milestone.py", "dcortex/v10_developmental_loop.py",
               "gateway/__init__.py", "gateway/epistemic_search.py", "gateway/memory_service_backend.py",
               "gateway/perspective_synthesis.py", "gateway/continuous_learning.py",
               "gateway/web_search.py", "gateway/internal_clock.py", "byon_mcp/__init__.py",
               "app/__init__.py", "run_byon.py"]

# Canonical relation seed (Phase 8). Stored as facts in memory-service (no parallel graph).
_RELATIONS = [
    ("BYON", "has_component", "D_Cortex"),
    ("BYON", "has_component", "FCE-M v15.7a"),
    ("BYON", "has_component", "FAISS semantic memory-service"),
    ("BYON", "role", "epistemic auditor and orchestrator (Worker / Auditor / Executor)"),
    ("BYON", "operational_level", "Level 2 of 4 (FULL_LEVEL3_NOT_DECLARED)"),
    ("BYON", "epistemic_contract", "answer only if grounded in valid committed memory, else UNKNOWN"),
    ("Claude", "role", "language and reasoning and hypothesis faculty"),
    ("Claude", "not_role", "truth authority"),
    ("FCE-M", "function", "advisory consolidation memory: provisional to committed to retrograde"),
    ("D_Cortex", "function", "additive morphogenetic addressable persistent chronodynamic memory"),
    ("memory-service", "function", "canonical FAISS semantic memory plus trust tiers plus FCE-M"),
    ("web search", "role", "optional evidence source, never automatic truth"),
]


def md_heading_chunks(text: str, max_chars: int = 1100) -> List[Tuple[str, str]]:
    """Split markdown into (heading, chunk) pieces, keeping each under max_chars."""
    lines = text.splitlines()
    chunks: List[Tuple[str, str]] = []
    heading = "(intro)"
    buf: List[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if not body:
            return
        if len(body) <= max_chars:
            chunks.append((heading, body))
        else:
            for i in range(0, len(body), max_chars):
                chunks.append((heading, body[i:i + max_chars]))

    for ln in lines:
        if re.match(r"^#{1,6}\s+", ln):
            flush()
            buf = []
            heading = ln.lstrip("#").strip()[:80] or "(section)"
        else:
            buf.append(ln)
    flush()
    return chunks


def _docstring(text: str) -> Optional[str]:
    m = re.search(r'"""(.*?)"""', text, re.S)
    return m.group(1).strip() if m else None


def train_self(memory_url: str, *, repo_root, mem_client=None,
               files: Optional[List[str]] = None) -> Dict[str, Any]:
    client = mem_client or MemoryServiceClient(memory_url)
    root = Path(repo_root)
    doc_files = files if files is not None else _DOC_FILES
    code_files = [] if files is not None else _CODE_FILES

    chunks_stored = 0
    used_files: List[str] = []
    trust_tiers: Dict[str, int] = {}

    def store(chunk: str, *, rel: str, heading: str):
        nonlocal chunks_stored
        client.store_fact(chunk, source=f"repo:{rel}#{heading}",
                          tags=["self_knowledge", "repo", rel, heading[:40]],
                          thread_id=None, trust="VERIFIED_PROJECT_FACT")
        chunks_stored += 1
        trust_tiers["VERIFIED_PROJECT_FACT"] = trust_tiers.get("VERIFIED_PROJECT_FACT", 0) + 1

    for rel in doc_files:
        p = root / rel
        if not p.exists():
            continue
        used_files.append(rel)
        for heading, chunk in md_heading_chunks(p.read_text(encoding="utf-8", errors="ignore")):
            store(chunk, rel=rel, heading=heading)

    for rel in code_files:
        p = root / rel
        if not p.exists():
            continue
        ds = _docstring(p.read_text(encoding="utf-8", errors="ignore"))
        if ds:
            used_files.append(rel)
            store(f"Module {rel}: {ds[:1100]}", rel=rel, heading="module docstring")

    # relation seed (Phase 8) — canonical facts in memory-service, no parallel graph
    relations_stored = 0
    if files is None:
        for subj, rel, tgt in _RELATIONS:
            client.store_fact(f"{subj} {rel.replace('_', ' ')} {tgt}",
                              source=f"relation:{subj}->{rel}->{tgt}",
                              tags=["relation", "self_knowledge", subj, tgt],
                              thread_id=None, trust="VERIFIED_PROJECT_FACT")
            relations_stored += 1
            chunks_stored += 1
            trust_tiers["VERIFIED_PROJECT_FACT"] = trust_tiers.get("VERIFIED_PROJECT_FACT", 0) + 1

    consolidated = None
    try:
        consolidated = client.fce_consolidate().get("fce_status")
    except Exception:
        consolidated = "unavailable"

    return {"files": len(used_files), "files_list": used_files, "chunks_stored": chunks_stored,
            "relations_stored": relations_stored, "trust_tiers": trust_tiers,
            "consolidated": consolidated, "scope": "system (thread_id=None)"}
