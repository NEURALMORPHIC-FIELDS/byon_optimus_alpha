"""Tests for the live evaluation harness (Gate 1).

Unit-portable: verifies the harness loads and exposes the criteria. The actual live run is
performed against a running gateway and is skipped here when none is reachable."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("httpx")

_HARNESS = Path(__file__).resolve().parents[1] / "scripts" / "live_byon_eval.py"


def _load():
    spec = importlib.util.spec_from_file_location("live_byon_eval", _HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_harness_module_loads_and_has_api():
    m = _load()
    assert hasattr(m, "Harness") and hasattr(m.Harness, "run") and hasattr(m.Harness, "research")
    assert str(m.REPORT).endswith("live_byon_eval_report.json")


def test_harness_covers_all_pass_criteria():
    import inspect
    src = inspect.getsource(_load().Harness.run)
    for gate in ["1_identity", "2_capabilities", "3_memory_state", "4_dynamics", "5_proof",
                 "6_chat_history", "7_followup", "8_memory_action", "9_vault", "10_secret",
                 "11a_teach", "12_unknown_weboff", "13_isolation"]:
        assert gate in src, f"harness missing criterion {gate}"


@pytest.mark.live
def test_live_eval_all_pass_if_gateway_up():
    import httpx
    m = _load()
    try:
        httpx.get("http://127.0.0.1:8090/v1/health", timeout=3)
    except Exception:
        pytest.skip("no live gateway on :8090")
    rep = m.Harness("http://127.0.0.1:8090").run()
    failed = [r["gate"] for r in rep["results"] if not r["pass"]]
    assert rep["all_pass"], f"live eval failures: {failed}"
