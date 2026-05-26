"""Tests for the InternalResearchClock (stress + budget + extensions)."""
from __future__ import annotations

import importlib

ic = importlib.import_module("gateway.internal_clock")


def _clock_at(elapsed, deadline=300.0, **kw):
    return ic.InternalResearchClock(deadline_seconds=deadline, started_at=0.0,
                                    time_fn=lambda: float(elapsed), **kw)


def test_base_stress_scales_with_elapsed():
    assert _clock_at(0).stress_percent() == 0.0
    assert _clock_at(150).stress_percent() == 50.0
    assert _clock_at(300).stress_percent() == 100.0


def test_pressure_accelerators_add_stress():
    c = _clock_at(0)
    c.add_pressure("conflict", ic.PRESSURE_SOURCES_CONFLICT)
    c.add_pressure("web_fail", ic.PRESSURE_WEB_FAIL)
    assert c.stress_percent() == 25.0  # 0 base + 15 + 10


def test_stress_bands():
    assert _clock_at(0).band() == "broaden"
    assert _clock_at(200).band() == "narrow"      # ~66%
    assert _clock_at(270).band() == "synthesize"  # 90%
    assert _clock_at(300).band() == "limit"       # 100%


def test_deadline_reached_and_extension():
    c = _clock_at(300, deadline=300.0, max_extensions=1)
    assert c.deadline_reached() is True
    assert c.can_extend() is True
    assert c.extend() is True
    assert c.deadline_seconds == 600.0 and c.extension_count == 1
    assert c.deadline_reached() is False        # 300 < 600 now
    assert c.can_extend() is False              # max_extensions=1
    assert c.extend() is False


def test_snapshot_shape():
    snap = _clock_at(60).snapshot()
    for k in ("elapsed_seconds", "stress_percent", "phase", "band", "deadline_seconds",
              "extension_count", "deadline_reached", "events"):
        assert k in snap
