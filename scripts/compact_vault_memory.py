#!/usr/bin/env python
"""Vault memory compaction (Cycle 5, target 4).

Retire pre-Cycle-4 DUPLICATE vault facts safely — by TOMBSTONE, never physical delete. Groups the
owner's vault facts by content, keeps the newest active copy, and tombstones the older duplicates.
Canonical / system facts are never tombstoned; verified-project facts only with --allow-verified.

  python scripts/compact_vault_memory.py                 # DRY-RUN (default): report duplicates
  python scripts/compact_vault_memory.py --apply         # tombstone older duplicates
  python scripts/compact_vault_memory.py --apply --allow-verified   # operator flag for VERIFIED

Report -> runtime/vaults/{vault_hash}/compaction_report.json. The core `compact()` is pure
(takes a client + tombstone store) so it is unit-tested without a live service.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gateway.memory_service_client import MemoryServiceClient   # noqa: E402
from gateway.tombstones import TombstoneStore, content_sha, CANONICAL_TRUSTS  # noqa: E402


def _vault_hits(mc: Any, owner: str) -> List[Dict[str, Any]]:
    hits = mc.search_facts("vault note", top_k=20000, threshold=0.0, thread_id=owner, scope="thread")
    return [h for h in (hits or [])
            if str((h.get("metadata") or {}).get("source", "")).startswith("vault:")]


def _source_id(hit: Dict[str, Any]) -> Optional[str]:
    for t in (hit.get("metadata") or {}).get("tags") or []:
        if isinstance(t, str) and t.startswith("source_id:"):
            return t.split("source_id:", 1)[1]
    return None


def compact(mc: Any, tomb: TombstoneStore, *, owner: str, apply: bool = False,
            allow_verified: bool = False) -> Dict[str, Any]:
    vault = _vault_hits(mc, owner)
    active_before = sum(1 for h in vault if not tomb.is_tombstoned(h))
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for h in vault:
        if tomb.is_tombstoned(h):
            continue
        groups[content_sha(h.get("content") or "")].append(h)

    duplicates_found = kept = tombstoned = skipped = errors = 0
    for sha, group in groups.items():
        if len(group) <= 1:
            kept += 1
            continue
        # newest first: prefer higher ctx_id, then later timestamp
        group.sort(key=lambda h: (h.get("ctx_id") or 0,
                                  (h.get("metadata") or {}).get("timestamp") or 0), reverse=True)
        kept += 1                                   # keep the newest copy
        for dup in group[1:]:
            duplicates_found += 1
            trust = (dup.get("metadata") or {}).get("trust")
            if trust == "SYSTEM_CANONICAL" or (trust in CANONICAL_TRUSTS and not allow_verified):
                skipped += 1                        # never retire canonical/verified without flag
                continue
            if not apply:
                tombstoned += 1                     # dry-run: would-tombstone
                continue
            r = tomb.tombstone(ctx_id=dup.get("ctx_id"), source_id=_source_id(dup),
                               content_sha_value=sha, reason="vault dedup compaction",
                               trust=trust, operator=allow_verified)
            if r.get("ok") and (r.get("tombstoned") or r.get("idempotent")):
                tombstoned += 1
            elif r.get("refused"):
                skipped += 1
            else:
                errors += 1
    active_after = active_before - (tombstoned if apply else 0)
    return {"dry_run": not apply, "owner": owner, "duplicates_found": duplicates_found,
            "kept": kept, "tombstoned": tombstoned, "skipped": skipped, "errors": errors,
            "active_before": active_before, "active_after": active_after,
            "tombstoned_total": tomb.active_count(),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _vault_hash() -> str:
    try:
        r = json.loads(Path("runtime/training/vault_train_report.json").read_text(encoding="utf-8"))
        return str(r.get("vault_hash", "default"))
    except Exception:
        return "default"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--owner", default="lucian")
    ap.add_argument("--apply", action="store_true", help="tombstone duplicates (default: dry-run)")
    ap.add_argument("--allow-verified", action="store_true",
                    help="operator flag: also retire VERIFIED_PROJECT_FACT duplicates")
    args = ap.parse_args()
    mc = MemoryServiceClient(args.url)
    tomb = TombstoneStore()
    rep = compact(mc, tomb, owner=args.owner, apply=args.apply, allow_verified=args.allow_verified)
    out = Path("runtime/vaults") / _vault_hash() / "compaction_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
