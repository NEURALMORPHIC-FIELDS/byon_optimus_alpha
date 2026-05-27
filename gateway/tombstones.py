# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Tombstone overlay (Cycle 5, target 3/5).

Old pre-Cycle-4 duplicate vault facts must be retired WITHOUT physical deletion (the canonical
memory-service has no delete API and must not be rewritten). A tombstone marks a specific fact
instance inactive: normal search excludes it; `include_tombstoned=True` still returns it for
audit; the operation is logged and reversible. Tombstoning a SYSTEM_CANONICAL / VERIFIED_PROJECT_
FACT requires an explicit operator flag.

Matching is precise (per instance) by `ctx_id`, with `source_id` / `content_sha` as fallbacks,
so compaction can retire duplicate copies while keeping one.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

CANONICAL_TRUSTS = {"SYSTEM_CANONICAL", "VERIFIED_PROJECT_FACT"}


def content_sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def _hit_keys(hit: Dict[str, Any]) -> Dict[str, Any]:
    md = hit.get("metadata") or {}
    src = md.get("source") or hit.get("source") or ""
    sid = ""
    for t in md.get("tags") or []:
        if isinstance(t, str) and t.startswith("source_id:"):
            sid = t.split("source_id:", 1)[1]
            break
    return {"ctx_id": hit.get("ctx_id") if hit.get("ctx_id") is not None else md.get("ctx_id"),
            "source": src, "source_id": sid,
            "content_sha": content_sha(hit.get("content") or "")}


class TombstoneStore:
    def __init__(self, *, path: str = "runtime/tombstones/tombstones.jsonl",
                 audit_path: str = "runtime/tombstones/tombstone_audit.jsonl") -> None:
        self.path = Path(path)
        self.audit_path = Path(audit_path)
        self._records: Dict[str, Dict[str, Any]] = {}   # key -> latest record (active flag)
        self._ctx: set = set()
        self._sid: set = set()
        self._sha: set = set()
        self._mtime: float = 0.0
        self._load()

    @staticmethod
    def _key(ctx_id, source_id, csha) -> str:
        if ctx_id is not None:
            return f"ctx:{ctx_id}"
        if source_id:
            return f"sid:{source_id}"
        return f"sha:{csha}"

    def maybe_reload(self) -> None:
        """Re-read the tombstone ledger if it changed on disk (another process - the harness or
        compaction - may have written tombstones since this store was loaded)."""
        try:
            mt = self.path.stat().st_mtime if self.path.exists() else 0.0
        except OSError:
            return
        if mt != self._mtime:
            self._records.clear()
            self._load()

    def _load(self) -> None:
        try:
            self._mtime = self.path.stat().st_mtime if self.path.exists() else 0.0
        except OSError:
            self._mtime = 0.0
        if not self.path.exists():
            self._rebuild_sets()
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
                self._records[rec["key"]] = rec
        except OSError:
            pass
        self._rebuild_sets()

    def _rebuild_sets(self) -> None:
        self._ctx = {r.get("ctx_id") for r in self._records.values()
                     if r.get("active") and r.get("ctx_id") is not None}
        self._sid = {r.get("source_id") for r in self._records.values()
                     if r.get("active") and r.get("source_id")}
        self._sha = {r.get("content_sha") for r in self._records.values()
                     if r.get("active") and r.get("by_content_sha") and r.get("content_sha")}

    def _append(self, rec: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._records[rec["key"]] = rec
        self._rebuild_sets()
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            pass

    def _audit(self, rec: Dict[str, Any]) -> None:
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # -- API ----------------------------------------------------------------
    def tombstone(self, *, ctx_id: Optional[int] = None, source_id: Optional[str] = None,
                  content_sha_value: Optional[str] = None, reason: str = "",
                  trust: Optional[str] = None, canonical: bool = False, operator: bool = False,
                  by_content_sha: bool = False, audit_trace_id: Optional[str] = None) -> Dict[str, Any]:
        if not reason or not str(reason).strip():
            return {"ok": False, "error": "reason is required"}
        if ctx_id is None and not source_id and not content_sha_value:
            return {"ok": False, "error": "ctx_id, source_id or content_sha required"}
        is_canon = bool(canonical) or (trust in CANONICAL_TRUSTS)
        if is_canon and not operator:
            return {"ok": False, "refused": "tombstoning canonical/verified requires operator=True",
                    "canonical": True}
        key = self._key(ctx_id, source_id, content_sha_value)
        existing = self._records.get(key)
        if existing and existing.get("active"):
            return {"ok": True, "idempotent": True, "key": key}   # already tombstoned
        rec = {"key": key, "ctx_id": ctx_id, "source_id": source_id,
               "content_sha": content_sha_value, "by_content_sha": by_content_sha,
               "reason": str(reason), "trust": trust, "canonical": is_canon, "operator": operator,
               "active": True, "tombstoned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "audit_trace_id": audit_trace_id}
        self._append(rec)
        self._audit({**rec, "action": "tombstone"})
        return {"ok": True, "key": key, "tombstoned": True}

    def revive(self, *, ctx_id=None, source_id=None, content_sha_value=None,
               reason: str = "revive") -> Dict[str, Any]:
        key = self._key(ctx_id, source_id, content_sha_value)
        if key not in self._records:
            return {"ok": False, "error": "not tombstoned"}
        rec = dict(self._records[key])
        rec["active"] = False
        rec["revived_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        rec["reason"] = reason
        self._append(rec)
        self._audit({**rec, "action": "revive"})
        return {"ok": True, "key": key, "revived": True}

    def is_tombstoned(self, hit: Dict[str, Any]) -> bool:
        # lazy: only do the work each tombstone type requires (avoid hashing every hit when there
        # are no content-sha tombstones).
        md = hit.get("metadata") or {}
        cid = hit.get("ctx_id") if hit.get("ctx_id") is not None else md.get("ctx_id")
        if self._ctx and cid is not None and cid in self._ctx:
            return True
        if self._sid:
            for t in md.get("tags") or []:
                if isinstance(t, str) and t.startswith("source_id:") and t.split("source_id:", 1)[1] in self._sid:
                    return True
        if self._sha and content_sha(hit.get("content") or "") in self._sha:
            return True
        return False

    def filter(self, hits: List[Dict[str, Any]], *, include_tombstoned: bool = False
               ) -> List[Dict[str, Any]]:
        if include_tombstoned:
            return list(hits)
        return [h for h in hits if not self.is_tombstoned(h)]

    def active_count(self) -> int:
        return len([1 for r in self._records.values() if r.get("active")])

    def counts(self) -> Dict[str, int]:
        return {"tombstoned_active": self.active_count(),
                "ctx": len(self._ctx), "source_id": len(self._sid), "content_sha": len(self._sha)}
