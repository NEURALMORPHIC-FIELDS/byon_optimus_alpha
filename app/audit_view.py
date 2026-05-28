# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Helpers to render BYON output for the UI (audit trace + compact summaries)."""
from __future__ import annotations

import json
from typing import Any, Dict


def render_audit(client: Any, trace_id: str) -> Any:
    if not trace_id:
        return "Audit trace not available."
    out = client.audit_trace(trace_id)
    if not out.get("ok"):
        return out.get("message", "Audit trace not available.")
    return json.dumps(out.get("trace", {}), indent=2, ensure_ascii=False)


def compact(obj: Any) -> str:
    if obj is None:
        return "-"
    if isinstance(obj, dict) and not obj:
        return "-"
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)
