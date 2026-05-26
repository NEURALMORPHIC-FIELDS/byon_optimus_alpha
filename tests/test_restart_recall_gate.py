"""Cycle 3 Pillar 2 — two-phase restart-recall gate (unit-portable).

The HTTP call is injected, so prepare()/verify() are tested without a live gateway or a real
restart. The actual cross-restart run is exercised live by scripts/live_restart_recall_eval.py.
"""
from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("httpx")

_spec = importlib.util.spec_from_file_location(
    "live_restart_recall_eval",
    str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts" / "live_restart_recall_eval.py"))
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)


def _fake_post(responses):
    """responses: dict user_id -> response dict; records the calls made."""
    calls = []

    def post(path, payload):
        calls.append(payload)
        return responses.get(payload["user_id"], {"epistemic_status": "UNKNOWN", "answer": ""})
    return post, calls


def test_restart_marker_written(tmp_path):
    marker = tmp_path / "restart_marker.json"
    post, _ = _fake_post({rr.USER: {"epistemic_status": "KNOWN", "answer": "my mountain is Retezat"}})
    out = rr.prepare(post=post, marker_path=marker)
    assert marker.exists()
    on_disk = json.loads(marker.read_text(encoding="utf-8"))
    assert on_disk["phase"] == "prepared" and on_disk["user"] == rr.USER
    assert on_disk["pre_restart_recall_ok"] is True


def test_restart_verify_uses_same_user(tmp_path):
    marker = tmp_path / "restart_marker.json"
    rep_path = tmp_path / "restart_recall_report.json"
    # prepare first (writes marker)
    p_post, _ = _fake_post({rr.USER: {"epistemic_status": "KNOWN", "answer": "Retezat"}})
    rr.prepare(post=p_post, marker_path=marker)
    # verify: same user recalls KNOWN/Retezat from memory-service, other user gets nothing
    v_post, calls = _fake_post({
        rr.USER: {"epistemic_status": "KNOWN", "answer": "my mountain is Retezat",
                  "source_class": "USER_MEMORY_GROUNDED"},
        rr.OTHER_USER: {"epistemic_status": "UNKNOWN", "answer": ""}})
    rep = rr.verify(post=v_post, marker_path=marker, report_path=rep_path)
    assert rep["same_user_recall_ok"] is True and rep["same_user_status"] == "KNOWN"
    assert any(c["user_id"] == rr.USER for c in calls)   # the same user was queried
    assert rep["passed"] is True and rep_path.exists()


def test_restart_verify_cross_user_no_leak(tmp_path):
    marker = tmp_path / "restart_marker.json"
    rr.prepare(post=_fake_post({rr.USER: {"epistemic_status": "KNOWN", "answer": "Retezat"}})[0],
               marker_path=marker)
    # cross-user LEAK must fail the gate
    leak_post, _ = _fake_post({
        rr.USER: {"epistemic_status": "KNOWN", "answer": "Retezat"},
        rr.OTHER_USER: {"epistemic_status": "KNOWN", "answer": "your mountain is Retezat"}})
    rep = rr.verify(post=leak_post, marker_path=marker, report_path=tmp_path / "r.json")
    assert rep["cross_user_leak"] is True and rep["cross_user_ok"] is False
    assert rep["passed"] is False


def test_restart_gate_skips_with_reason_if_not_configured(tmp_path):
    # verify without a marker -> skipped with an explicit reason, never a false pass
    rep = rr.verify(post=lambda p, x: {}, marker_path=tmp_path / "missing.json")
    assert rep["passed"] is False and rep.get("skipped") is True
    assert "prepare" in rep["error"]
    assert "BYON_EVAL_RESTART_PHASE" in rr.skip_reason()
