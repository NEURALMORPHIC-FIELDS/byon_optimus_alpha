# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Internal research task queue (Cycle 6, target 3).

When LifeLoop v2 sees a repeated unknown / unresolved topic, it files an internal ResearchTask -
a NOTE TO SELF to look harder, not an answer. Memory / vault / self-state research can be
scheduled automatically; WEB research requires user permission unless BYON_ALLOW_AUTONOMOUS_WEB
is set. Tasks never run on secrets and are idempotent by topic. The queue holds no truth.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

PENDING = "pending"
RUNNING = "running"
BLOCKED_NEEDS_PERMISSION = "blocked_needs_permission"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
OPEN_STATUSES = {PENDING, RUNNING, BLOCKED_NEEDS_PERMISSION}

MEMORY_SOURCES = {"memory", "vault", "self_state"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def autonomous_web_allowed() -> bool:
    return os.environ.get("BYON_ALLOW_AUTONOMOUS_WEB", "false").strip().lower() in ("1", "true", "yes", "on")


class ResearchTaskQueue:
    def __init__(self, path: str = "runtime/lifeloop/research_tasks.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.tasks[t["task_id"]] = t           # last record per id wins
        except OSError:
            pass

    def _append(self, task: Dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(task, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self.tasks[task["task_id"]] = task

    # -- creation (idempotent by topic) ------------------------------------
    def by_topic(self, topic: str) -> Optional[Dict[str, Any]]:
        for t in self.tasks.values():
            if t["topic"] == topic and t["status"] in OPEN_STATUSES:
                return t
        return None

    def create(self, *, topic: str, question: str, trigger_event_ids: Optional[List[str]] = None,
               priority: float = 1.0, allowed_sources: Optional[List[str]] = None,
               is_secret: bool = False) -> Optional[Dict[str, Any]]:
        if is_secret:
            return None                                # never a research task for a secret
        with self._lock:
            existing = self.by_topic(topic)
            if existing:                               # idempotent by topic
                if trigger_event_ids:
                    existing["trigger_event_ids"] = (existing.get("trigger_event_ids", []) +
                                                     trigger_event_ids)[-20:]
                    existing["priority"] = round(existing.get("priority", 1.0) + 0.5, 3)
                    existing["updated_at"] = _now()
                    self._append(existing)
                return existing
            allowed = allowed_sources or ["memory", "vault", "self_state"]
            wants_web = "web" in allowed
            needs_perm = wants_web and not autonomous_web_allowed()
            task = {
                "task_id": "rt_" + uuid.uuid4().hex[:10], "topic": topic, "question": question,
                "trigger_event_ids": trigger_event_ids or [], "priority": priority,
                "allowed_sources": allowed,
                "status": BLOCKED_NEEDS_PERMISSION if needs_perm else PENDING,
                "requires_user_permission": needs_perm,
                "created_at": _now(), "updated_at": _now(), "result": None}
            self._append(task)
            return task

    # -- lifecycle ----------------------------------------------------------
    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.tasks.get(task_id)

    def set_status(self, task_id: str, status: str, *, result: Any = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            t = self.tasks.get(task_id)
            if not t:
                return None
            t["status"] = status
            t["updated_at"] = _now()
            if result is not None:
                t["result"] = result
            self._append(t)
            return t

    def approve_web(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            t = self.tasks.get(task_id)
            if not t:
                return None
            t["requires_user_permission"] = False
            t["status"] = PENDING
            t["updated_at"] = _now()
            self._append(t)
            return t

    def cancel(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.set_status(task_id, CANCELLED)

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        out = [t for t in self.tasks.values() if status is None or t["status"] == status]
        return sorted(out, key=lambda t: (-t.get("priority", 0), t.get("created_at", "")))

    def pending(self) -> List[Dict[str, Any]]:
        return [t for t in self.tasks.values() if t["status"] in OPEN_STATUSES]

    def counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {}
        for t in self.tasks.values():
            c[t["status"]] = c.get(t["status"], 0) + 1
        return c
