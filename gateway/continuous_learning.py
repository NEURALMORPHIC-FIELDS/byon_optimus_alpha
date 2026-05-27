# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Continuous learning as an interaction side-effect - over the canonical memory-service.

The authoritative semantic memory is the BYON memory-service (FAISS + FCE-M + trust tiers).
This module does NOT duplicate it. It adds only the per-user *lifecycle / evidence* ledgers
that the memory-service does not expose (the Explore audit confirmed it has no evidence
counting): candidates accumulate evidence here and, once they cross the threshold, are
PROMOTED into the memory-service with a committed trust tier and an FCE-M consolidation.

Per-user files (lifecycle ledgers, not a parallel semantic store):
    events.jsonl            every interaction
    research_traces.jsonl   one row per research turn
    memory_candidates.jsonl provisional facts + evidence_count (drives promotion)
    facts.jsonl             local mirror of committed promotions (for the UI memory panel)
    archive.jsonl           retrograded / disputed history
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

EVIDENCE_THRESHOLD = int(os.environ.get("BYON_CONSOLIDATION_EVIDENCE_THRESHOLD", "2"))


def _key(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())[:120]


class ContinuousLearning:
    def __init__(self, namespace_dir: str | Path, mem_client: Optional[Any] = None,
                 thread_id: Optional[str] = None) -> None:
        self.dir = Path(namespace_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.mem = mem_client
        self.thread_id = thread_id

    # -- low level -----------------------------------------------------------
    def _p(self, name: str) -> Path:
        return self.dir / name

    def _append(self, name: str, row: Dict[str, Any]) -> None:
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **row}
        with self._p(name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _load(self, name: str) -> List[Dict[str, Any]]:
        p = self._p(name)
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _rewrite(self, name: str, rows: List[Dict[str, Any]]) -> None:
        self._p(name).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
            encoding="utf-8")

    # -- A. interaction event (always logged) --------------------------------
    def record_event(self, kind: str, **fields: Any) -> None:
        self._append("events.jsonl", {"kind": kind, **fields})

    def record_research_trace(self, trace: Dict[str, Any]) -> None:
        self._append("research_traces.jsonl", trace)

    # -- candidates / evidence ----------------------------------------------
    def upsert_candidate(self, value: str, *, source_type: str, sources: Optional[List[str]] = None,
                         question: str = "", delta_evidence: int = 1) -> Dict[str, Any]:
        rows = self._load("memory_candidates.jsonl")
        k = _key(value)
        found = None
        for r in rows:
            if r.get("key") == k:
                found = r
                break
        if found is None:
            found = {"key": k, "value": value, "source_type": source_type,
                     "sources": sources or [], "evidence_count": 0, "status": "candidate",
                     "question": question}
            rows.append(found)
        found["evidence_count"] += delta_evidence
        if sources:
            found["sources"] = sorted(set((found.get("sources") or []) + sources))
        self._rewrite("memory_candidates.jsonl", rows)
        # mirror into the canonical memory-service as an UNCOMMITTED candidate fact
        if self.mem is not None and delta_evidence > 0:
            try:
                self.mem.store_fact(value, source=";".join(sources or [source_type]),
                                    tags=["candidate", source_type], thread_id=self.thread_id,
                                    trust=None)
            except Exception:
                pass
        return found

    def store_web_candidate(self, value: str, sources: List[str], question: str = "") -> Dict[str, Any]:
        c = self.upsert_candidate(value, source_type="web", sources=sources, question=question)
        self.record_event("web_candidate", value=value, sources=sources, evidence=c["evidence_count"])
        return c

    def reinforce(self, value: str, delta: int = 1) -> Dict[str, Any]:
        c = self.upsert_candidate(value, source_type="acceptance", delta_evidence=delta)
        self.record_event("reinforce", value=value, evidence=c["evidence_count"])
        return c

    def list_candidates(self) -> List[Dict[str, Any]]:
        return [r for r in self._load("memory_candidates.jsonl") if r.get("status") == "candidate"]

    def list_committed(self) -> List[Dict[str, Any]]:
        return self._load("facts.jsonl")

    def list_disputed(self) -> List[Dict[str, Any]]:
        return [r for r in self._load("archive.jsonl") if r.get("status") == "disputed"]

    # -- F. contradiction ----------------------------------------------------
    def dispute(self, value: str, reason: str = "contradiction") -> None:
        self._append("archive.jsonl", {"value": value, "status": "disputed", "reason": reason})
        if self.mem is not None:
            try:
                self.mem.store_fact(value, source="dispute", tags=["disputed"],
                                    thread_id=self.thread_id, trust="DISPUTED_OR_UNSAFE",
                                    disputed=True, disputed_pattern=reason)
            except Exception:
                pass
        self.record_event("dispute", value=value, reason=reason)

    # -- G. consolidation: promote well-evidenced candidates -> committed ----
    def consolidate(self, threshold: int = EVIDENCE_THRESHOLD) -> Dict[str, Any]:
        rows = self._load("memory_candidates.jsonl")
        promoted: List[str] = []
        for r in rows:
            if r.get("status") == "candidate" and r.get("evidence_count", 0) >= threshold:
                r["status"] = "committed"
                self._append("facts.jsonl", {"value": r["value"], "source_type": r.get("source_type"),
                                             "sources": r.get("sources", []),
                                             "evidence_count": r["evidence_count"]})
                promoted.append(r["value"])
                if self.mem is not None:  # promote into canonical memory with a committed trust tier
                    try:
                        self.mem.store_fact(r["value"], source=";".join(r.get("sources") or []),
                                            tags=["committed", r.get("source_type", "")],
                                            thread_id=self.thread_id, trust="VERIFIED_PROJECT_FACT")
                    except Exception:
                        pass
        self._rewrite("memory_candidates.jsonl", rows)
        fce = {}
        if self.mem is not None:
            try:
                fce = self.mem.fce_consolidate()
            except Exception:
                fce = {"fce_status": "unavailable"}
        self.record_event("consolidate", promoted=promoted, threshold=threshold)
        return {"promoted": promoted, "promoted_count": len(promoted), "fce": fce}
