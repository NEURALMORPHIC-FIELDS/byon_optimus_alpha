"""InternalResearchClock — chronodynamic research budget + stress engine.

BYON does not search forever and does not give up instantly. A research turn runs against
a real-time budget (default 300s). Stress rises with elapsed time and with pressure
accelerators (conflict, web failure, high-certainty demand, low reliability, unsafe topic).
Stress drives behaviour: broaden → narrow → synthesize → ask permission. At the real
deadline BYON asks the user for more time instead of silently continuing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# pressure accelerators (percent added to stress)
PRESSURE_SOURCES_CONFLICT = 15.0
PRESSURE_WEB_FAIL = 10.0
PRESSURE_HIGH_CERTAINTY = 10.0
PRESSURE_LOW_RELIABILITY = 10.0
PRESSURE_UNSAFE_TOPIC = 20.0

PHASES = ("memory", "claude", "web", "synthesis", "permission", "done")


@dataclass
class InternalResearchClock:
    deadline_seconds: float = 300.0
    extension_seconds: float = 300.0
    max_extensions: int = 1
    time_fn: Callable[[], float] = time.time
    started_at: Optional[float] = None
    bonus_stress: float = 0.0
    phase: str = "memory"
    extension_count: int = 0
    events: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.started_at is None:   # 0.0 is a valid explicit start, do not override it
            self.started_at = self.time_fn()

    def elapsed_seconds(self) -> float:
        return max(0.0, self.time_fn() - self.started_at)

    def base_stress(self) -> float:
        return min(100.0, self.elapsed_seconds() / max(1e-6, self.deadline_seconds) * 100.0)

    def stress_percent(self) -> float:
        return min(100.0, self.base_stress() + self.bonus_stress)

    def add_pressure(self, reason: str, pct: float) -> None:
        self.bonus_stress = min(100.0, self.bonus_stress + pct)
        self.events.append({"t": round(self.elapsed_seconds(), 3), "pressure": reason, "pct": pct})

    def set_phase(self, phase: str) -> None:
        if phase in PHASES:
            self.phase = phase
            self.events.append({"t": round(self.elapsed_seconds(), 3), "phase": phase})

    def band(self) -> str:
        s = self.stress_percent()
        if s < 60:
            return "broaden"        # 0-60%: normal search
        if s < 85:
            return "narrow"         # 60-85%: highest-quality sources only
        if s < 100:
            return "synthesize"     # 85-99%: bounded answer from current evidence
        return "limit"             # 100%: permission / bounded / unknown

    def deadline_reached(self) -> bool:
        """True only when REAL elapsed time has reached the (possibly extended) deadline."""
        return self.elapsed_seconds() >= self.deadline_seconds

    def can_extend(self) -> bool:
        return self.extension_count < self.max_extensions

    def extend(self) -> bool:
        if not self.can_extend():
            return False
        self.deadline_seconds += self.extension_seconds
        self.extension_count += 1
        self.events.append({"t": round(self.elapsed_seconds(), 3),
                            "extension": self.extension_count,
                            "new_deadline": self.deadline_seconds})
        return True

    def snapshot(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at,
            "elapsed_seconds": round(self.elapsed_seconds(), 3),
            "stress_percent": round(self.stress_percent(), 1),
            "phase": self.phase,
            "band": self.band(),
            "deadline_seconds": self.deadline_seconds,
            "extension_count": self.extension_count,
            "max_extensions": self.max_extensions,
            "deadline_reached": self.deadline_reached(),
            "events": list(self.events),
        }
