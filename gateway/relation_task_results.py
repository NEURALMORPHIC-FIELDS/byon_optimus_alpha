# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Cluj-Napoca, Romania
"""Relation gap-repair task-result ingestion (Cycle 15 TRACK E).

Records a completed gap-repair task result append-only and routes it through the candidate /
relation lifecycle: evidence becomes a CANDIDATE (or reinforces the relation), a contradiction
creates a DISPUTED challenger, and an empty result stays UNRESOLVED (no fabrication). It NEVER
commits directly and NEVER decides truth, FCE-M may influence PRIORITY only, never truth, and the
relation field is never a truth authority. The committing path remains the existing consolidation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_RESULTS_LOG = "runtime/lifeloop/relation_task_results.jsonl"
_EVIDENCE_STATUSES = {"KNOWN", "PROVISIONAL", "PROVISIONAL_UNVERIFIED", "ACTION_DONE"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ingest_relation_task_result(*, gap: Dict[str, Any], result: Dict[str, Any],
                                field: Optional[Any] = None, lifecycle: Optional[Any] = None,
                                pressure_delta: float = 0.0,
                                log_path: str = DEFAULT_RESULTS_LOG) -> Dict[str, Any]:
    """Ingest one gap-repair result. Returns the recorded row. Candidate/relation lifecycle only;
    never commits, never fabricates."""
    result = result or {}
    status = result.get("epistemic_status")
    sources = result.get("sources_used") or []
    subject, obj = gap.get("subject", ""), gap.get("object", "")
    rid = gap.get("relation_id")
    task_type = gap.get("gap_type")
    task_id = result.get("task_id") or gap.get("task_id")
    evidence_found = status in _EVIDENCE_STATUSES and bool((result.get("answer_summary")
                                                            or result.get("answer") or sources))
    contradiction = status == "DISPUTED"
    candidate_created = relation_updated = False
    candidate_id = None

    if contradiction and field is not None:
        # DISPUTED challenger: a contradiction edge (never deletes the original, never commits)
        try:
            field.add_relation(subject, "contradicts", obj, is_contradiction=True,
                               source_id=f"taskchallenge:{task_id}",
                               source_class=result.get("source_class") or "PROVISIONAL_WEB",
                               evidence_quote=(result.get("answer_summary") or "")[:160])
            relation_updated = True
        except Exception:
            pass
    elif evidence_found:
        if lifecycle is not None and hasattr(lifecycle, "ingest_task_result"):
            try:
                cand = lifecycle.ingest_task_result(
                    task_id=task_id, topic=gap.get("topic", f"relgap:{rid}"),
                    claim=(result.get("answer_summary") or result.get("answer") or "")[:300],
                    sources_used=sources, epistemic_status=status,
                    source_class=result.get("source_class"), source_event_ids=[rid] if rid else [],
                    is_secret=False) or {}
                candidate_id = cand.get("candidate_id")
                candidate_created = bool(candidate_id)
            except Exception:
                pass
        elif field is not None and subject and obj:
            # reinforce the relation in the field (adds a source; stays a candidate, never commits)
            try:
                field.add_relation(subject, gap.get("predicate", "depends_on"), obj,
                                   source_id=f"taskreinforce:{task_id}",
                                   source_class=result.get("source_class") or "EXTRACTED_USER_CLAIM")
                relation_updated = True
            except Exception:
                pass

    row = {
        "task_id": task_id, "gap_id": rid, "relation_id": rid, "task_type": task_type,
        "sources_used": sources, "evidence_found": evidence_found,
        "candidate_created": candidate_created, "candidate_id": candidate_id,
        "relation_updated": relation_updated, "pressure_delta": pressure_delta,
        "epistemic_status": status, "committed_directly": False,
        "fce_influence": "priority_only (never truth)",
        "result_summary": (result.get("answer_summary") or "")[:200] if evidence_found
                           else ("unresolved: no evidence found (kept open, not fabricated)"),
        "timestamp": _now()}
    p = Path(log_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return row


def read_relation_task_results(log_path: str = DEFAULT_RESULTS_LOG, *, last: int = 20) -> list:
    p = Path(log_path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-last:]
        return [json.loads(x) for x in lines if x.strip()]
    except (OSError, ValueError):
        return []
