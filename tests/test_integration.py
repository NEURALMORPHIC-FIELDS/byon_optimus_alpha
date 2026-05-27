"""Integration / live assertions over artifacts produced by the runners.

These read the JSON artifacts emitted by `orchestration/integrate.py` and the v10 loop.
They are skipped when the artifacts are absent, so the fast suite stays green offline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTEG = PROJECT_ROOT / "runtime" / "integration_results"
E2E = INTEG / "byon-dcortex-v99-live-e2e" / "byon-dcortex-v99-live-e2e.json"
V10 = PROJECT_ROOT / "runtime" / "v10_out" / "v10_developmental_loop_report.json"


@pytest.mark.integration
def test_memory_service_boot_and_organ_injected():
    report = INTEG / "integration_report.json"
    if not report.exists():
        pytest.skip("no integration_report.json - run orchestration/integrate.py")
    r = json.loads(report.read_text(encoding="utf-8"))
    assert r.get("success") is True
    assert r["memory_health"]["status"] == "healthy"
    status = r["dcortex_status_start"]["dcortex_v99"]
    assert status["enabled"] is True and status["source_exists"] is True
    assert r["dcortex_grounding_packet"]["packet"]["enabled"] is True


@pytest.mark.live
def test_live_e2e_three_gated_probes_pass():
    if not E2E.exists():
        pytest.skip("no live E2E artifact - run integrate.py with a live ANTHROPIC_API_KEY")
    s = json.loads(E2E.read_text(encoding="utf-8"))
    assert s["model"].startswith("claude")
    assert s["probe_count"] == 3
    by = {r["expected"]: r["pass"] for r in s["results"]}
    assert by.get("known") is True
    assert by.get("boundary") is True
    assert by.get("unknown") is True
    assert s["passes"] is True


@pytest.mark.slow
def test_v10_developmental_loop_mechanisms():
    if not V10.exists():
        pytest.skip("no v10 report - run dcortex.v10_developmental_loop")
    r = json.loads(V10.read_text(encoding="utf-8"))
    c = r["criteria"]
    # the core mechanisms must hold (capacity/interference is reported, not gated here)
    assert c["learning_occurs"] is True
    assert c["reload_retained"] is True
    assert c["addressing_is_causal"] is True
    assert c["memory_is_causal"] is True
    assert c["adversarial_source_resilient"] is True
    assert c["contradiction_resisted"] is True
