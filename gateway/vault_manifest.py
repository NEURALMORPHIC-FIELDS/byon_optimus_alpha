"""Content-addressed vault dedup manifest (Cycle 4, target 2).

Re-indexing a vault must NOT re-store unchanged chunks. This manifest is content-addressed at
the CHUNK level: each chunk has a stable `source_id` and a `chunk_sha256`. Before storing, we
skip a chunk whose sha is already active. When a file changes, its old chunks are marked
`superseded` (the memory-service has no delete API, so we track lifecycle here and simply avoid
duplicate writes).

Append-only JSONL at runtime/vaults/{vault_hash}/manifest.jsonl — crash-safe; on load, the last
record per chunk_id wins. Records: file_path, file_sha256, chunk_id, chunk_sha256,
memory_ctx_id, indexed_at, status (active | superseded | tombstoned | error).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_TOMBSTONED = "tombstoned"
STATUS_ERROR = "error"


def chunk_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def file_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def source_id(rel_path: str, index: int, chunk_sha: str) -> str:
    """Stable content-addressed id: obsidian:<relative_path>#chunk:<index>:<sha>."""
    return f"obsidian:{rel_path}#chunk:{index}:{chunk_sha[:16]}"


class VaultManifest:
    def __init__(self, vault_hash: str, *, base: str = "runtime/vaults") -> None:
        self.vault_hash = vault_hash
        self.dir = Path(base) / vault_hash
        self.path = self.dir / "manifest.jsonl"
        self._by_chunk: Dict[str, Dict[str, Any]] = {}   # chunk_id -> latest record
        self._active_shas: set = set()                   # O(1) dedup by content sha
        self.bootstrapped = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cid = rec.get("chunk_id")
                if cid:
                    self._by_chunk[cid] = rec   # last record wins
        except OSError:
            pass
        self._rebuild_active_shas()

    def _rebuild_active_shas(self) -> None:
        self._active_shas = {r.get("chunk_sha256") for r in self._by_chunk.values()
                             if r.get("status") == STATUS_ACTIVE and r.get("chunk_sha256")}

    def _append(self, rec: Dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._by_chunk[rec["chunk_id"]] = rec
        if rec.get("status") == STATUS_ACTIVE and rec.get("chunk_sha256"):
            self._active_shas.add(rec["chunk_sha256"])

    def bootstrap_from_memory(self, mem_client: Any, owner: str, *, top_k: int = 20000) -> int:
        """Pre-populate the dedup set from vault facts ALREADY in the memory-service, so a
        re-index does not re-store content that is already there. Returns count bootstrapped.
        Idempotent: only runs when the manifest has no active chunks yet."""
        if self._active_shas:
            return 0
        try:
            hits = mem_client.search_facts("vault note", top_k=top_k, threshold=0.0,
                                           thread_id=owner, scope="thread")
        except Exception:
            return 0
        per_file: Dict[str, int] = {}
        n = 0
        for h in hits or []:
            src = str((h.get("metadata") or {}).get("source", ""))
            if not src.startswith("vault:"):
                continue
            content = h.get("content") or ""
            if not content:
                continue
            rel = src[len("vault:"):].split("#", 1)[0]
            csha = chunk_sha256(content)
            if csha in self._active_shas:
                continue
            idx = per_file.get(rel, 0)
            per_file[rel] = idx + 1
            self.record_chunk(rel_path=rel, file_sha=None, index=idx, chunk_sha=csha,
                              memory_ctx_id=(h.get("metadata") or {}).get("ctx_id"),
                              status=STATUS_ACTIVE)
            n += 1
        self.bootstrapped = n
        return n

    # -- queries ------------------------------------------------------------
    def active_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        rec = self._by_chunk.get(chunk_id)
        return rec if rec and rec.get("status") == STATUS_ACTIVE else None

    def has_active_chunk_sha(self, chunk_sha: str) -> bool:
        return chunk_sha in self._active_shas

    def file_sha(self, rel_path: str) -> Optional[str]:
        """Current active file sha for a path (None if no active chunks for it)."""
        for r in self._by_chunk.values():
            if r.get("file_path") == rel_path and r.get("status") == STATUS_ACTIVE:
                return r.get("file_sha256")
        return None

    def active_chunk_ids_for_file(self, rel_path: str) -> List[str]:
        return [cid for cid, r in self._by_chunk.items()
                if r.get("file_path") == rel_path and r.get("status") == STATUS_ACTIVE]

    # -- mutations ----------------------------------------------------------
    def record_chunk(self, *, rel_path: str, file_sha: str, index: int, chunk_sha: str,
                     memory_ctx_id: Any = None, status: str = STATUS_ACTIVE) -> str:
        cid = source_id(rel_path, index, chunk_sha)
        self._append({"file_path": rel_path, "file_sha256": file_sha, "chunk_id": cid,
                      "chunk_sha256": chunk_sha, "memory_ctx_id": memory_ctx_id,
                      "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "status": status})
        return cid

    def supersede_file(self, rel_path: str) -> int:
        """Mark all active chunks of a (now-changed) file as superseded. Returns count."""
        n = 0
        for cid in self.active_chunk_ids_for_file(rel_path):
            old = dict(self._by_chunk[cid])
            old["status"] = STATUS_SUPERSEDED
            old["superseded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._append(old)
            n += 1
        if n:
            self._rebuild_active_shas()   # a sha may have gone inactive
        return n

    def record_error(self, rel_path: str, message: str) -> None:
        self._append({"file_path": rel_path, "file_sha256": None,
                      "chunk_id": f"error:{rel_path}:{time.time()}", "chunk_sha256": None,
                      "memory_ctx_id": None,
                      "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "status": STATUS_ERROR, "message": message[:300]})

    # -- stats --------------------------------------------------------------
    def counts(self) -> Dict[str, int]:
        c = {STATUS_ACTIVE: 0, STATUS_SUPERSEDED: 0, STATUS_TOMBSTONED: 0, STATUS_ERROR: 0}
        for r in self._by_chunk.values():
            c[r.get("status", STATUS_ACTIVE)] = c.get(r.get("status", STATUS_ACTIVE), 0) + 1
        return c

    def active_files(self) -> int:
        return len({r.get("file_path") for r in self._by_chunk.values()
                    if r.get("status") == STATUS_ACTIVE})

    def active_sha_count(self) -> int:
        """Distinct active CONTENT shas (deduped) — the true count of unique indexed chunks,
        which is what the memory-service vault-fact count should agree with. Counting records
        instead would double-count a sha recorded under both a bootstrap and a real index."""
        return len(self._active_shas)
