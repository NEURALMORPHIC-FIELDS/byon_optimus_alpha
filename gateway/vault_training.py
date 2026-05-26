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


def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    import json as _json
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)   # atomic on the same filesystem


def train_vault(memory_url: str, *, vault_path: str, mem_client=None,
                owner: Optional[str] = None, verified_folders: Optional[List[str]] = None,
                report_dir: str = "runtime/training", max_files: Optional[int] = None,
                resume: bool = True) -> Dict[str, Any]:
    import json as _json
    import time as _time
    client = mem_client or MemoryServiceClient(memory_url)
    vault = Path(vault_path)
    if not vault.exists():
        _atomic_write_json(Path(report_dir) / "vault_train_report.json",
                           {"vault": str(vault_path), "error": "vault not found", "files": 0,
                            "chunks_stored": 0, "partial": True})
        return {"error": f"vault not found: {vault_path}", "files": 0, "chunks_stored": 0}
    owner = owner or os.environ.get("BYON_VAULT_OWNER", "lucian")
    verified = set(verified_folders or [])
    # resume manifest: relpath -> sha of the last-indexed content (skip unchanged on rerun)
    manifest_path = Path(report_dir) / "vault_manifest.json"
    manifest: Dict[str, str] = {}
    if resume:
        try:
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        except (OSError, _json.JSONDecodeError):
            manifest = {}
    started = _time.time()

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

    chunks_stored = files_indexed = files_scanned = skipped = errors = 0
    tags_seen: set = set()
    trust_tiers: Dict[str, int] = {}
    total_notes = len(notes)
    last_completed_file = ""
    vault_hash = hashlib.sha256("|".join(sorted(note_names.values())).encode()).hexdigest()[:12]
    report_path = Path(report_dir) / "vault_train_report.json"

    def _report(partial: bool, completed: bool = False) -> Dict[str, Any]:
        try:
            vault_facts = client.search_facts("vault note", top_k=1, threshold=0.0,
                                              thread_id=owner, scope="thread")
        except Exception:
            vault_facts = []
        rep = {
            "vault": str(vault), "owner": owner, "notes_total": total_notes,
            "files_scanned": files_scanned, "files_indexed": files_indexed, "files": files_indexed,
            "chunks_stored": chunks_stored, "facts_stored": chunks_stored, "skipped": skipped,
            "errors": errors, "duration_s": round(_time.time() - started, 2),
            "last_completed_file": last_completed_file, "vault_hash": vault_hash,
            "backlinks": sum(len(v) for v in backlinks.values()),
            "tags": sorted(tags_seen)[:40], "trust_tiers": trust_tiers,
            "partial": partial and not completed, "complete": completed,
            "max_files": max_files,
        }
        try:
            _atomic_write_json(report_path, rep)
        except Exception:
            pass
        return rep

    consolidated = None
    for p in notes:
        if max_files is not None and files_indexed >= max_files:
            break
        rel = str(p.relative_to(vault)).replace("\\", "/")
        files_scanned += 1
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            errors += 1
            continue
        sha = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
        if resume and manifest.get(rel) == sha:   # unchanged since last run -> skip
            skipped += 1
            continue
        fm = _parse_frontmatter(text)
        tags = _tags(text, fm)
        tags_seen.update(tags)
        top_folder = rel.split("/", 1)[0] if "/" in rel else ""
        trust = "VERIFIED_PROJECT_FACT" if top_folder in verified else "EXTRACTED_USER_CLAIM"
        note_backlinks = backlinks.get(rel, [])
        try:
            for heading, chunk in md_heading_chunks(text):
                note_tags = ["vault", f"note:{rel}", f"heading:{heading[:40]}", f"sha:{sha}"] + \
                            [f"tag:{t}" for t in tags[:8]] + \
                            ([f"backlink:{b}" for b in note_backlinks[:5]])
                client.store_fact(chunk, source=f"vault:{rel}#{heading}", tags=note_tags,
                                  thread_id=owner, trust=trust)
                chunks_stored += 1
                trust_tiers[trust] = trust_tiers.get(trust, 0) + 1
        except Exception:
            errors += 1
            continue
        files_indexed += 1
        last_completed_file = rel
        manifest[rel] = sha
        if files_indexed % 10 == 0:
            _report(partial=True)
            try:
                _atomic_write_json(manifest_path, manifest)
            except Exception:
                pass

    try:
        consolidated = client.fce_consolidate().get("fce_status")
    except Exception:
        consolidated = "unavailable"
    try:
        _atomic_write_json(manifest_path, manifest)
    except Exception:
        pass
    # complete iff we scanned every note and were not capped by max_files
    completed = (files_scanned >= total_notes) and not (max_files is not None and files_indexed >= max_files
                                                        and files_scanned < total_notes)
    rep = _report(partial=not completed, completed=completed)
    rep["consolidated"] = consolidated
    return rep
