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
from . import vault_errors as ve
from .vault_manifest import VaultManifest, chunk_sha256, file_sha256, source_id
from .write_lock import VaultTrainingLock

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
                resume: bool = True, use_lock: bool = True,
                vaults_base: str = "runtime/vaults", progress_every: int = 25) -> Dict[str, Any]:
    """Index an Obsidian vault into the canonical memory-service with: a single-writer lock,
    content-addressed chunk dedup (re-index does not re-store), encoding-aware reads, per-file
    error classification, and a coherent resumable report (partial until every eligible note is
    scanned; stale=false only when the report agrees with the memory-service vault-fact count)."""
    import time as _time
    client = mem_client or MemoryServiceClient(memory_url)
    vault = Path(vault_path)
    report_path = Path(report_dir) / "vault_train_report.json"
    if not vault.exists():
        _atomic_write_json(report_path,
                           {"vault_path": str(vault_path), "vault": str(vault_path),
                            "error": "vault not found", "files": 0, "files_scanned": 0,
                            "chunks_stored": 0, "partial": True, "complete": False, "stale": True})
        return {"error": f"vault not found: {vault_path}", "files": 0, "chunks_stored": 0}
    owner = owner or os.environ.get("BYON_VAULT_OWNER", "lucian")
    verified = set(verified_folders or [])
    started = _time.time()

    # -- single-writer lock: refuse a second concurrent trainer -------------
    lock = VaultTrainingLock()
    lock_info: Dict[str, Any] = {"used": use_lock}
    if use_lock:
        res = lock.acquire(vault_path=str(vault), command="train_vault")
        lock_info.update(res)
        if not res["acquired"]:
            rep = {"vault_path": str(vault), "vault": str(vault), "owner": owner,
                   "error": "another vault trainer is active", "lock": res,
                   "files_scanned": 0, "files_indexed": 0, "chunks_stored": 0,
                   "partial": True, "complete": False, "stale": True}
            _atomic_write_json(report_path, rep)
            return rep

    try:
        return _run_index(client, vault, owner, verified, report_path, report_dir, vaults_base,
                          max_files, resume, progress_every, started, lock, lock_info)
    finally:
        if use_lock:
            lock.release()


def _run_index(client, vault, owner, verified, report_path, report_dir, vaults_base,
               max_files, resume, progress_every, started, lock, lock_info) -> Dict[str, Any]:
    import time as _time

    # first pass: wikilink graph for backlinks (encoding-safe; never crashes on a bad note)
    outgoing: Dict[str, List[str]] = {}
    note_names: Dict[str, str] = {}
    notes = list(_iter_notes(vault))
    for p in notes:
        rel = str(p.relative_to(vault)).replace("\\", "/")
        note_names[p.stem.lower()] = rel
        txt, _err = ve.read_markdown(p)
        outgoing[rel] = [t.strip() for t in _WIKILINK.findall(txt or "")]
    backlinks: Dict[str, List[str]] = {}
    for src, links in outgoing.items():
        for tgt in links:
            tgt_rel = note_names.get(tgt.lower())
            if tgt_rel:
                backlinks.setdefault(tgt_rel, []).append(src)

    total_notes = len(notes)
    # vault identity is the PATH (stable across runs even as notes are added/removed) so the
    # resume manifest persists; a separate content hash tracks the current note set.
    try:
        vault_key = str(vault.resolve())
    except OSError:
        vault_key = str(vault)
    vault_hash = hashlib.sha256(vault_key.encode()).hexdigest()[:12]
    content_hash = hashlib.sha256("|".join(sorted(note_names.values())).encode()).hexdigest()[:12]
    manifest = VaultManifest(vault_hash, base=vaults_base)
    errlog = ve.VaultErrorLog(vault_hash, base=vaults_base)
    if not resume:
        errlog.reset_file()
    # dedup against what is ALREADY in the memory-service (so a re-index does not re-store)
    bootstrapped = manifest.bootstrap_from_memory(client, owner) if resume else 0

    chunks_stored = chunks_dedup = files_indexed = files_scanned = skipped = errors = superseded = 0
    tags_seen: set = set()
    trust_tiers: Dict[str, int] = {}
    last_completed_file = ""

    def _vault_facts_in_memory() -> int:
        try:
            hits = client.search_facts("vault note", top_k=20000, threshold=0.0,
                                       thread_id=owner, scope="thread")
        except Exception:
            return -1
        return sum(1 for h in hits
                   if str((h.get("metadata") or {}).get("source", "")).startswith("vault:"))

    def _report(completed: bool) -> Dict[str, Any]:
        in_memory = _vault_facts_in_memory()
        active_chunks = manifest.active_sha_count()   # distinct content (deduped), not records
        # AGREE iff complete AND memory holds at least every distinct active chunk we tracked.
        if in_memory < 0:
            stale = True
        else:
            stale = (not completed) or (active_chunks > 0 and in_memory < active_chunks)
        duration = round(_time.time() - started, 2)
        rep = {
            "vault_path": str(vault), "vault": str(vault), "owner": owner, "vault_hash": vault_hash,
            "content_hash": content_hash,
            "notes_total": total_notes, "eligible_files": total_notes,
            "files_scanned": files_scanned, "files_indexed": files_indexed, "files": files_indexed,
            "files_skipped": skipped, "skipped": skipped,
            "chunks_stored": chunks_stored, "facts_stored": chunks_stored,
            "facts_extracted": chunks_stored, "chunks_skipped_dedup": chunks_dedup,
            "chunks_superseded": superseded, "manifest_active_chunks": active_chunks,
            "manifest_counts": manifest.counts(), "bootstrapped_from_memory": bootstrapped,
            "errors": errors, "errors_by_type": errlog.counts_by_type(),
            "duration_seconds": duration, "duration_s": duration,
            "last_completed_file": last_completed_file,
            "backlinks": sum(len(v) for v in backlinks.values()),
            "tags": sorted(tags_seen)[:40],
            "trust_tier_distribution": dict(trust_tiers), "trust_tiers": trust_tiers,
            "vault_facts_in_memory": in_memory,
            "partial": not completed, "complete": completed, "stale": bool(stale),
            "max_files": max_files, "lock": lock_info,
            "errors_report": str(errlog.path), "manifest_path": str(manifest.path),
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
        lock.heartbeat()
        text, read_err = ve.read_markdown(p)
        if read_err:
            errlog.log(rel, read_err["error_type"], read_err["message"], read_err["phase"],
                       read_err["recoverable"])
            errors += 1
            if text is None:        # unreadable / skipped (binary, too large, permission) -> next
                manifest.record_error(rel, read_err["message"])
                continue
        f_sha = file_sha256(text)
        prev = manifest.file_sha(rel)
        if resume and prev == f_sha:                    # file unchanged since last index -> skip
            skipped += 1
            continue
        if prev and prev != f_sha:                      # file changed -> retire its old chunks
            superseded += manifest.supersede_file(rel)
        try:
            fm = _parse_frontmatter(text)
            tags = _tags(text, fm)
        except Exception as exc:                        # frontmatter parse error -> log, continue
            etype, rec = ve.classify_exception(exc, "frontmatter")
            errlog.log(rel, etype, str(exc), "frontmatter", rec)
            errors += 1
            fm, tags = {}, []
        tags_seen.update(tags)
        top_folder = rel.split("/", 1)[0] if "/" in rel else ""
        trust = "VERIFIED_PROJECT_FACT" if top_folder in verified else "EXTRACTED_USER_CLAIM"
        note_backlinks = backlinks.get(rel, [])
        file_had_error = False
        try:
            chunks = md_heading_chunks(text)
        except Exception as exc:
            etype, rec = ve.classify_exception(exc, "chunk")
            errlog.log(rel, etype, str(exc), "chunk", rec)
            errors += 1
            chunks = []
        for i, (heading, chunk) in enumerate(chunks):
            csha = chunk_sha256(chunk)
            if manifest.has_active_chunk_sha(csha):     # content-addressed dedup -> do not re-store
                manifest.record_chunk(rel_path=rel, file_sha=f_sha, index=i, chunk_sha=csha)
                chunks_dedup += 1
                continue
            note_tags = ["vault", f"note:{rel}", f"heading:{heading[:40]}", f"sha:{f_sha[:12]}",
                         f"source_id:{source_id(rel, i, csha)}"] + \
                        [f"tag:{t}" for t in tags[:8]] + \
                        ([f"backlink:{b}" for b in note_backlinks[:5]])
            try:
                res = client.store_fact(chunk, source=f"vault:{rel}#{heading}", tags=note_tags,
                                        thread_id=owner, trust=trust)
                ctx_id = res.get("ctx_id") if isinstance(res, dict) else None
            except Exception as exc:
                etype, rec = ve.classify_exception(exc, "store")
                errlog.log(rel, etype, str(exc), "store", rec)
                errors += 1
                file_had_error = True
                continue
            manifest.record_chunk(rel_path=rel, file_sha=f_sha, index=i, chunk_sha=csha,
                                  memory_ctx_id=ctx_id)
            chunks_stored += 1
            trust_tiers[trust] = trust_tiers.get(trust, 0) + 1
        if not file_had_error:
            files_indexed += 1
            last_completed_file = rel
        if files_scanned % progress_every == 0:
            _report(completed=False)

    try:
        consolidated = client.fce_consolidate().get("fce_status")
    except Exception:
        consolidated = "unavailable"
    completed = (files_scanned >= total_notes) and not (
        max_files is not None and files_indexed >= max_files and files_scanned < total_notes)
    rep = _report(completed=completed)
    rep["consolidated"] = consolidated
    return rep
