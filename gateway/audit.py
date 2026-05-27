# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Audit trace store.

Every message that enters the Gateway gets a trace_id and an audit record, written
both to a global audit dir (retrievable by trace_id) and to the user's namespace.
The record captures the request, the BYON verdict, and the grounding/memory summary
- enough to answer 'why did the user get this answer / refusal?' after the fact.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


def new_trace_id() -> str:
    return "trace_" + uuid.uuid4().hex


class AuditLog:
    def __init__(self, audit_root: str | Path) -> None:
        self.root = Path(audit_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _file(self, trace_id: str) -> Path:
        # trace_id is generated internally (uuid4) so it is path-safe.
        return self.root / f"{trace_id}.json"

    def write(self, trace_id: str, record: Dict[str, Any],
              user_namespace_dir: Optional[Path] = None) -> Path:
        record = {"trace_id": trace_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  **record}
        payload = json.dumps(record, indent=2, default=str)
        path = self._file(trace_id)
        path.write_text(payload, encoding="utf-8")
        if user_namespace_dir is not None:
            try:
                ua = Path(user_namespace_dir) / "audit" / f"{trace_id}.json"
                ua.parent.mkdir(parents=True, exist_ok=True)
                ua.write_text(payload, encoding="utf-8")
            except OSError:
                pass  # global record is the source of truth; per-user copy is best-effort
        return path

    def read(self, trace_id: str) -> Optional[Dict[str, Any]]:
        path = self._file(trace_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def count(self) -> int:
        return sum(1 for _ in self.root.glob("trace_*.json"))
