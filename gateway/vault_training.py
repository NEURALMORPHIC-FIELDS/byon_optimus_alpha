"""Phase 4 — Obsidian vault training (the user's living corpus).

Reads markdown notes (frontmatter, tags, wikilinks, backlinks, headings, path, mtime, sha256),
heading-aware chunks → canonical memory-service store (FAISS) → FCE-M consolidate. Vault notes
are USER memory, NOT automatically objective truth: default trust EXTRACTED_USER_CLAIM (a
configured verified-folder list may raise to VERIFIED_PROJECT_FACT). Stored under the vault
owner's thread for per-user isolation.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .memory_service_client import MemoryServiceClient
from .self_training import md_heading_chunks

_IGNORE_DIRS = {".obsidian", ".git", ".trash", "trash", "node_modules", "secrets", ".obsidian.vimrc"}
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
_TAG = re.compile(r"(?:^|\s)#([A-Za-z0-9_\-/]+)")
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _parse_frontmatter(text: str) -> Dict[str, Any]:
    m = _FRONTMATTER.match(text)
    if not m:
        return {}
    fm: Dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def _tags(text: str, fm: Dict[str, Any]) -> List[str]:
    tags = set(_TAG.findall(text))
    raw = fm.get("tags", "")
    for t in re.split(r"[,\[\]\s]+", str(raw)):
        if t.strip():
            tags.add(t.strip())
    return sorted(tags)


def _iter_notes(vault: Path):
    for p in vault.rglob("*.md"):
        if any(part in _IGNORE_DIRS for part in p.relative_to(vault).parts):
            continue
        yield p


def train_vault(memory_url: str, *, vault_path: str, mem_client=None,
                owner: Optional[str] = None, verified_folders: Optional[List[str]] = None) -> Dict[str, Any]:
    client = mem_client or MemoryServiceClient(memory_url)
    vault = Path(vault_path)
    if not vault.exists():
        return {"error": f"vault not found: {vault_path}", "files": 0, "chunks_stored": 0}
    owner = owner or os.environ.get("BYON_VAULT_OWNER", "lucian")
    verified = set(verified_folders or [])

    # first pass: build the wikilink graph (note -> outgoing links) for backlinks
    outgoing: Dict[str, List[str]] = {}
    note_names: Dict[str, str] = {}  # lowercased stem -> relpath
    notes = list(_iter_notes(vault))
    for p in notes:
        rel = str(p.relative_to(vault)).replace("\\", "/")
        note_names[p.stem.lower()] = rel
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            txt = ""
        outgoing[rel] = [t.strip() for t in _WIKILINK.findall(txt)]
    backlinks: Dict[str, List[str]] = {}
    for src, links in outgoing.items():
        for tgt in links:
            tgt_rel = note_names.get(tgt.lower())
            if tgt_rel:
                backlinks.setdefault(tgt_rel, []).append(src)

    chunks_stored = 0
    files = 0
    tags_seen: set = set()
    trust_tiers: Dict[str, int] = {}

    for p in notes:
        rel = str(p.relative_to(vault)).replace("\\", "/")
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files += 1
        fm = _parse_frontmatter(text)
        tags = _tags(text, fm)
        tags_seen.update(tags)
        sha = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
        top_folder = rel.split("/", 1)[0] if "/" in rel else ""
        trust = "VERIFIED_PROJECT_FACT" if top_folder in verified else "EXTRACTED_USER_CLAIM"
        note_backlinks = backlinks.get(rel, [])
        for heading, chunk in md_heading_chunks(text):
            provenance = f"vault:{rel}#{heading}"
            note_tags = ["vault", f"note:{rel}", f"heading:{heading[:40]}", f"sha:{sha}"] + \
                        [f"tag:{t}" for t in tags[:8]] + \
                        ([f"backlink:{b}" for b in note_backlinks[:5]])
            client.store_fact(chunk, source=provenance, tags=note_tags,
                              thread_id=owner, trust=trust)
            chunks_stored += 1
            trust_tiers[trust] = trust_tiers.get(trust, 0) + 1

    consolidated = None
    try:
        consolidated = client.fce_consolidate().get("fce_status")
    except Exception:
        consolidated = "unavailable"

    return {"vault": str(vault), "owner": owner, "files": files, "chunks_stored": chunks_stored,
            "backlinks": sum(len(v) for v in backlinks.values()), "tags": sorted(tags_seen)[:40],
            "trust_tiers": trust_tiers, "consolidated": consolidated}
