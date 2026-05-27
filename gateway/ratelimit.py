# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Minimal per-user fixed-window rate limiter (in-process, alpha scope).

Not a distributed limiter - it bounds a single misbehaving alpha user per Gateway
process. A real deployment would back this with Redis; the interface stays the same.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List


class RateLimiter:
    def __init__(self, per_minute: int = 60) -> None:
        self.per_minute = max(1, per_minute)
        self._hits: Dict[str, List[float]] = defaultdict(list)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        window_start = now - 60.0
        hits = [t for t in self._hits[key] if t >= window_start]
        hits.append(now)
        self._hits[key] = hits
        return len(hits) <= self.per_minute
