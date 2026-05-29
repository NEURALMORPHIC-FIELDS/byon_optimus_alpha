# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Scheduled relation decay maintenance (Cycle 15 TRACK B).

A bounded, auditable pass over the relation field that recomputes temporal decay, flags weak
relations, and RECOMMENDS gap-repair tasks. It is NOT a truth authority: it never deletes a
relation, never commits, never decides truth. Canonical relations resist decay; disputed and
candidate relations decay faster (reusing the existing relation_decay model, which is computed on
read). The run is logged append-only to runtime/lifeloop/relation_maintenance_log.jsonl.

Also exposes build_gap_acquisition_context(): the acquisition_context (repo_root from
BYON_REPO_ROOT, plus optional corpus path / external-LLM models) that gap-repair must thread
through lifeloop_run_task -> backend.research -> EpistemicSearch.run so the existing 13.3
project_files / corpus / external-LLM adapters actually fire for find_internal_evidence and
verify_with_project_source. There is NO parallel acquisition path.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from gateway.relation_field import (CANDIDATE, COMMITTED, DISPUTED, RelationField, RelationGapScanner,
                                    relation_decay)

DEFAULT_LOG = "runtime/lifeloop/relation_maintenance_log.jsonl"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _is_canonical(r: Dict[str, Any]) -> bool:
    return r.get("origin") == "canonical_schema" or "SYSTEM_CANONICAL" in (r.get("source_classes") or [])


def build_gap_acquisition_context() -> Dict[str, Any]:
    """The acquisition_context gap-repair threads into EpistemicSearch.run so the 13.3 adapters fire.
    repo_root comes from BYON_REPO_ROOT (without it project_files stays dark - the confirmed
    asterisk); corpus path / external models are added only when configured."""
    ctx: Dict[str, Any] = {"repo_root": os.environ.get("BYON_REPO_ROOT", "").strip()}
    corpus = os.environ.get("BYON_CORPUS_PATH", "").strip()
    if corpus:
        ctx["corpus_path"] = corpus
    models = [m.strip() for m in os.environ.get("BYON_EXTERNAL_LLMS", "").split(",") if m.strip()]
    if models:
        ctx["external_models"] = models
    return ctx


def run_relation_decay_maintenance(field: RelationField, *, log_path: Optional[str] = DEFAULT_LOG,
                                   now_ts: Optional[float] = None, recent_days: float = 7.0,
                                   max_recommended: int = 12) -> Dict[str, Any]:
    """One scheduled decay-maintenance pass. Returns the report; appends it to the log. Never
    deletes, never commits, never decides truth."""
    start = time.time()
    now_ts = now_ts if now_ts is not None else time.time()
    rels = list(field._rel.values())
    relations_scanned = len(rels)
    relations_decayed = relations_reinforced_recently = 0
    canonical_resisted_decay = disputed_decayed = tombstoned_source_decayed = 0
    weak_relations_flagged: List[Dict[str, Any]] = []

    for r in rels:
        d = relation_decay(r, now_ts=now_ts)
        if d["decay_status"] == "disabled":
            continue
        status = r.get("status")
        canon = _is_canonical(r)
        if d["decay_factor"] < 1.0:
            relations_decayed += 1
        if canon and d["decay_factor"] >= 0.99:
            canonical_resisted_decay += 1
        if status == DISPUTED and d["decay_factor"] < 0.8:
            disputed_decayed += 1
        if r.get("tombstoned") and d["decay_factor"] < 0.5:
            tombstoned_source_decayed += 1
        ref = r.get("last_reinforced_at") or r.get("last_seen") or ""
        try:
            age_d = (now_ts - time.mktime(time.strptime(ref, "%Y-%m-%dT%H:%M:%SZ"))) / 86400.0
            if 0 <= age_d <= recent_days and int(r.get("reinforcement_count", 0)) > 0:
                relations_reinforced_recently += 1
        except (ValueError, TypeError):
            pass
        if d["decay_status"] == "stale" or status in (CANDIDATE, DISPUTED):
            r["last_maintenance_weak"] = True          # cached flag only; never deletes / commits
            weak_relations_flagged.append({
                "relation_id": r.get("relation_id"), "subject": r.get("subject"),
                "predicate": r.get("predicate"), "object": r.get("object"), "status": status,
                "decayed_weight": d["decayed_weight"], "decay_status": d["decay_status"],
                "canonical": canon})

    central_weak_nodes = field.weak_central_nodes(top_n=8)
    # RECOMMEND (never create) gap-repair tasks: the scanner with tasks=None only proposes.
    recommended_tasks = RelationGapScanner(field, tasks=None).scan(cap=max_recommended)

    report = {
        "maintenance_id": "maint_" + uuid.uuid4().hex[:10], "timestamp": _now(),
        "relations_scanned": relations_scanned, "relations_decayed": relations_decayed,
        "relations_reinforced_recently": relations_reinforced_recently,
        "canonical_resisted_decay": canonical_resisted_decay, "disputed_decayed": disputed_decayed,
        "tombstoned_source_decayed": tombstoned_source_decayed,
        "weak_relations_flagged": weak_relations_flagged,
        "central_weak_nodes": central_weak_nodes, "recommended_tasks": recommended_tasks,
        "duration_ms": round((time.time() - start) * 1000.0, 2),
        "never_deletes": True, "never_commits": True, "is_truth_authority": False,
    }
    if log_path:
        p = Path(log_path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(report, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return report


def read_maintenance_log(log_path: str = DEFAULT_LOG, *, last: int = 10) -> List[Dict[str, Any]]:
    p = Path(log_path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-last:]
        return [json.loads(x) for x in lines if x.strip()]
    except (OSError, ValueError):
        return []
