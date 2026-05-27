# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Per-user/session UI logs as JSONL. Never logs secrets or the API key."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slug(s: str) -> str:
    return _SAFE.sub("_", str(s).strip()).strip("._-") or "anon"


class UILogStore:
    def __init__(self, logs_dir: str | Path) -> None:
        self.root = Path(logs_dir)

    def path_for(self, user_id: str, session_id: str) -> Path:
        d = self.root / _slug(user_id)
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{_slug(session_id)}.jsonl"

    def append(self, *, user_id: str, session_id: str, message: str, response: str,
               epistemic_status: str, grounded: bool, audit_trace_id: str) -> Path:
        row: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "user_id": user_id, "session_id": session_id,
            "message": message, "response": response,
            "epistemic_status": epistemic_status, "grounded": grounded,
            "audit_trace_id": audit_trace_id,
        }
        p = self.path_for(user_id, session_id)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return p
