# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Read-consistent, tombstone-aware memory-service client wrapper (Cycle 5, targets 1/2/5).

The canonical memory-service is sealed (not rewritten); read-consistency and the tombstone
overlay are enforced at the client/gateway access boundary instead. This wrapper:

  * READ CONSISTENCY - a reader never observes a false zero/empty caused by an in-flight write
    burst: it detects an active writer (the vault_training write-lock), retries an empty result
    within an explicit timeout, and falls back to the last STABLE snapshot for a query if the
    burst keeps returning empty. `read_consistency_mode` is exposed for status.
  * TOMBSTONES - search excludes tombstoned facts by default (include_tombstoned=True for audit);
    rerank / source_policy / self-state therefore never see retired duplicates.
  * BATCH WRITES - store_facts_batch holds the write intent once per batch (not per chunk),
    preserves per-item source_id / source / trust / tags, and reports per-item ids and failures.

Everything else passes through to the base MemoryServiceClient unchanged.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from .engine_consistency import EngineConsistency
from .tombstones import TombstoneStore
from .write_lock import VaultTrainingLock

READ_CONSISTENCY_MODE = "rw_coordinated_snapshot+retry"


class ConsistentMemoryClient:
    def __init__(self, base: Any, *, tombstones: Optional[TombstoneStore] = None,
                 lock: Optional[VaultTrainingLock] = None, retries: int = 4,
                 retry_wait: float = 0.4, snapshot_ttl: float = 600.0,
                 engine: Optional[EngineConsistency] = None) -> None:
        self.base = base
        self.tomb = tombstones if tombstones is not None else TombstoneStore()
        self.lock = lock if lock is not None else VaultTrainingLock()
        self.engine = engine if engine is not None else EngineConsistency()
        self.retries = retries
        self.retry_wait = retry_wait
        self.snapshot_ttl = snapshot_ttl
        # in-engine RW coordination is the primary signal; snapshot+retry remains the fallback
        self.read_consistency_mode = self.engine.read_consistency_mode
        self.fallback_consistency_mode = READ_CONSISTENCY_MODE
        self._stable: Dict[str, Dict[str, Any]] = {}   # query-key -> {hits, ts}
        self.last_read_timed_out = False

    # passthrough for everything not overridden (store_fact, stats, health, fce_*, ...)
    def __getattr__(self, name):
        return getattr(self.base, name)

    def _write_in_progress(self) -> bool:
        try:
            return bool(self.lock.status().get("indexing_in_progress"))
        except Exception:
            return False

    @staticmethod
    def _key(query, kw) -> str:
        return f"{query}|{kw.get('thread_id')}|{kw.get('scope')}|{kw.get('top_k')}|{kw.get('threshold')}"

    # -- read-consistent, tombstone-filtered search -------------------------
    def search_facts(self, query: str, *, include_tombstoned: bool = False, **kw) -> List[Dict[str, Any]]:
        self.last_read_timed_out = False
        # in-engine coordination: wait for any active write batch to commit before reading, so the
        # reader never observes partial FAISS/metadata state (bounded by an explicit timeout).
        try:
            self.engine.wait_consistent(timeout=2.0)
        except Exception:
            pass
        hits = self.base.search_facts(query, **kw)
        # fallback consistency: a forced-empty during an active write burst must not be observed
        if not hits and self._write_in_progress():
            deadline = time.time() + self.retries * self.retry_wait
            while time.time() < deadline:
                time.sleep(self.retry_wait)
                hits = self.base.search_facts(query, **kw)
                if hits:
                    break
            if not hits:
                snap = self._stable.get(self._key(query, kw))
                if snap and (time.time() - snap["ts"]) <= self.snapshot_ttl:
                    self.last_read_timed_out = True          # explicit: served stale snapshot
                    hits = snap["hits"]
        if hits:                                              # refresh the stable snapshot
            self._stable[self._key(query, kw)] = {"hits": list(hits), "ts": time.time()}
        self.tomb.maybe_reload()                              # pick up tombstones written elsewhere
        return self.tomb.filter(hits, include_tombstoned=include_tombstoned)

    def vault_fact_count(self, owner: str, *, include_tombstoned: bool = False) -> Dict[str, Any]:
        """Consistent count of ACTIVE vault facts for an owner (never a false zero during a write)."""
        raw = self.search_facts("vault note", include_tombstoned=True, top_k=20000,
                                threshold=0.0, thread_id=owner, scope="thread")
        vault = [h for h in raw if str((h.get("metadata") or {}).get("source", "")).startswith("vault:")]
        active = self.tomb.filter(vault)
        return {"active": len(active), "tombstoned": len(vault) - len(active),
                "total": len(vault), "served_from_snapshot": self.last_read_timed_out}

    # -- batch writes -------------------------------------------------------
    def store_facts_batch(self, items: List[Dict[str, Any]], *,
                          batch_size: Optional[int] = None) -> Dict[str, Any]:
        """Store many facts holding the write intent once per batch (not per item). Each item:
        {fact, source, tags, thread_id, trust}. Returns per-item ctx_ids and any failures."""
        if batch_size is None:
            batch_size = int(os.environ.get("BYON_VAULT_WRITE_BATCH_SIZE", "50"))
        stored, failed = [], []
        for start in range(0, len(items), max(1, batch_size)):
            self.lock.heartbeat()
            for it in items[start:start + batch_size]:
                try:
                    res = self.base.store_fact(
                        it["fact"], source=it.get("source", ""), tags=it.get("tags") or [],
                        thread_id=it.get("thread_id"), trust=it.get("trust"))
                    stored.append({"source_id": it.get("source_id"),
                                   "ctx_id": (res or {}).get("ctx_id") if isinstance(res, dict) else None})
                except Exception as exc:
                    failed.append({"source_id": it.get("source_id"), "source": it.get("source"),
                                   "error": str(exc)[:200]})
        return {"stored": len(stored), "failed": len(failed), "ids": stored,
                "failed_items": failed, "batch_size": batch_size}

    # -- tombstone API ------------------------------------------------------
    def tombstone_fact(self, *, ctx_id=None, source_id=None, content_sha_value=None,
                       reason: str = "", trust=None, canonical: bool = False,
                       operator: bool = False, by_content_sha: bool = False,
                       audit_trace_id=None) -> Dict[str, Any]:
        return self.tomb.tombstone(ctx_id=ctx_id, source_id=source_id,
                                   content_sha_value=content_sha_value, reason=reason, trust=trust,
                                   canonical=canonical, operator=operator,
                                   by_content_sha=by_content_sha, audit_trace_id=audit_trace_id)

    def tombstone_counts(self) -> Dict[str, int]:
        self.tomb.maybe_reload()
        return self.tomb.counts()

    def engine_consistency_status(self) -> Dict[str, Any]:
        try:
            st = self.engine.status()
            st["fallback_mode"] = self.fallback_consistency_mode
            return st
        except Exception:
            return {"read_consistency_mode": self.fallback_consistency_mode}
