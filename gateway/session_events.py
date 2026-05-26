"""Literal per-session event stream (Cycle 2, target 3).

    runtime/users/{user_slug}/sessions/{session_id}/events.jsonl

An ADDITIONAL active-memory stream (the audit log is kept). Records every user message,
assistant response, research result, feedback and consolidation event with status / intent /
sources / audit_trace_id. FollowUpResolver and ChatHistorySummary prefer this stream and fall
back to the audit log only when it is missing. Not a semantic memory — just the session log.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe(s: str) -> str:
    return _SAFE.sub("_", str(s).strip()).strip("._-") or "default"


class SessionEvents:
    def __init__(self, namespace_dir: str | Path, session_id: str) -> None:
        self.session_id = session_id
        self.dir = Path(namespace_dir) / "sessions" / _safe(session_id)
        self.path = self.dir / "events.jsonl"

    def append(self, role: str, **fields: Any) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "session_id": self.session_id, "role": role, **fields}
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            return []
        return out

    def last_assistant(self) -> Optional[Dict[str, Any]]:
        for r in reversed(self.read()):
            if r.get("role") == "assistant":
                return r
        return None

    # convenience writers
    def log_turn(self, *, question: str, answer: str, epistemic_status: str, intent: Optional[str],
                 sources: Optional[List[str]], audit_trace_id: Optional[str]) -> None:
        self.append("user", message=question)
        self.append("assistant", answer=(answer or "")[:600], epistemic_status=epistemic_status,
                    intent=intent, sources=sources or [], audit_trace_id=audit_trace_id)
