"""Tests for the v10 — Longitudinal Generalization & Isolation milestone.

Fast unit tests (document parser, fail-hard FCE-M gate) always run. The full
eight-gate run is marked `slow` and skips when the real v15.7a engine is not
locally resolvable — REAL_FCEM_REQUIRED is mandatory, never silently faked.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

m = importlib.import_module("dcortex.v10_milestone")


def _engine_available() -> bool:
    root = m.resolve_fcem_engine_root()
    return bool(root) and (Path(root) / "d_cortex" / "__init__.py").exists()


def _strict_real_fcem() -> bool:
    """Release-validation profile. With BYON_VALIDATE_REAL_FCEM=true a missing real
    v15.7a engine is a HARD FAILURE, never a skip — REAL_FCEM_REQUIRED is mandatory
    in validation, only skippable in the unit-portable profile (dev-sheet §7.3)."""
    return os.environ.get("BYON_VALIDATE_REAL_FCEM", "").strip().lower() in (
        "1", "true", "yes", "on")


def _require_engine() -> None:
    if _engine_available():
        return
    if _strict_real_fcem():
        pytest.fail(
            "BYON_VALIDATE_REAL_FCEM=true but the real v15.7a d_cortex engine is not "
            "resolvable — REAL_FCEM_REQUIRED fails hard in release validation (no skip).")
    pytest.skip("real v15.7a d_cortex engine not resolvable locally (unit-portable profile)")


def test_doc_parser_extracts_locative_place_not_trailing_clause():
    """Regression: '... in Calder this year.' must resolve to Calder, not 'year'."""
    n = 6
    v_loc, place_loc = m._parse_doc_value(
        "Meridian Institute confirms its headquarters remain in Calder this year.", n)
    v_simple, place_simple = m._parse_doc_value(
        "The headquarters of the Meridian Institute is located in Calder.", n)
    assert place_loc == "Calder" and place_simple == "Calder"
    assert v_loc == v_simple  # same fact ⇒ same value index
    v_to, place_to = m._parse_doc_value(
        "Verified filings relocate the headquarters to Tarsus.", n)
    assert place_to == "Tarsus" and v_to != v_loc  # different fact ⇒ different index


def test_real_fcem_required_fails_hard_on_bogus_root(monkeypatch):
    """No diluted fallback (dev-sheet §7.3): a missing/shim engine must raise,
    never silently degrade to a stub."""
    monkeypatch.setenv("FCEM_MEMORY_ENGINE_ROOT", "/definitely/not/a/real/engine")
    with pytest.raises(m.RealFCEMRequiredError):
        m.load_real_fcem_adapter()


def test_real_fcem_adapter_is_sealed_v15_7a():
    _require_engine()
    proof = m.load_real_fcem_adapter()
    assert proof["adapter_class"] == "DCortexAdapter"
    assert proof["version"].startswith(m._SEALED_VERSION_PREFIX)
    assert proof["pipeline_ran"] is True


def test_fcem_advisory_effect_is_measurable():
    """Gate 7 in isolation: contested input must carry strictly more advisory
    pressure than aligned input, and OFF mode must stay silent."""
    _require_engine()
    fcem = m.load_real_fcem_adapter()
    g7 = m.gate_fcem_advisory_effect(fcem)
    assert g7["contested_max_pressure"] > g7["aligned_max_pressure"]
    assert g7["advisory_nonempty"] is True and g7["off_empty"] is True
    assert g7["passed"] is True


@pytest.mark.slow
def test_v10_milestone_all_eight_gates(tmp_path):
    _require_engine()
    report = m.run_v10_milestone(fast=True, outdir=tmp_path, seed=20261103)
    gates = report["gates"]
    assert gates["REAL_FCEM_REQUIRED"] is True
    assert gates["UNSEEN_DOMAIN_TRANSFER"] is True
    assert gates["REAL_OOV_UNKNOWN"] is True
    assert gates["DELAYED_RECALL_RESTART"] is True
    assert gates["CROSS_USER_ISOLATION"] is True
    assert gates["REAL_CONTRADICTION_STREAM"] is True
    assert gates["FCEM_ADVISORY_EFFECT"] is True
    assert gates["FALSE_ASSERTION_RATE_ZERO"] is True
    # the headline epistemic invariant: no ungrounded query was ever answered
    assert report["gate8_false_assertion_rate_zero"]["false_assertions"] == 0
    assert report["gate8_false_assertion_rate_zero"]["total_ungrounded_queries"] > 0
    assert report["verdict"] == "V10_LONGITUDINAL_VALIDATED"
    assert report["gates_passed"] == report["gates_total"] == 8
