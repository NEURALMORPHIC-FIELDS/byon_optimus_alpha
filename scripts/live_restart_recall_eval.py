#!/usr/bin/env python
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Two-phase restart-recall gate (Cycle 3, Pillar 2).

Makes "memory survives a restart" a REAL pass/fail gate instead of a manual note.

  Phase A (prepare): teach a stable fact for user `eval_restart_user`, confirm recall BEFORE the
                     restart, and write runtime/eval/restart_marker.json.
  Phase B (verify):  after the app has been restarted, recall the same fact as the SAME user
                     (expect KNOWN / Retezat / memory-service) and as a DIFFERENT user
                     (expect no leak). Writes runtime/eval/restart_recall_report.json.

Usage:
  python scripts/live_restart_recall_eval.py --phase prepare [--url ...]
  # (restart the app)
  python scripts/live_restart_recall_eval.py --phase verify  [--url ...]
  python scripts/live_restart_recall_eval.py --phase auto     # prepare, restart app, verify

The HTTP call is injectable (`post=`) so the phases are unit-testable without a live gateway.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

MARKER = Path("runtime/eval/restart_marker.json")
REPORT = Path("runtime/eval/restart_recall_report.json")

USER = "eval_restart_user"
OTHER_USER = "eval_restart_other"
FACT_SENTENCE = "remember that my restart test mountain is Retezat"
RECALL_Q = "what is my restart test mountain?"
EXPECT = "Retezat"
GOOD_CROSS_STATUSES = ("UNKNOWN", "ASK_USER_FOR_SOURCE", "PROVISIONAL_UNVERIFIED", "REFUSED")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _http_post(url: str) -> Callable[[str, Dict[str, Any]], Dict[str, Any]]:
    import httpx

    def post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        r = httpx.post(f"{url.rstrip('/')}{path}", json=payload, timeout=90.0)
        r.raise_for_status()
        return r.json()
    return post


def _research(post, user: str, session: str, question: str) -> Dict[str, Any]:
    return post("/v1/research", {"user_id": user, "session_id": session,
                                 "question": question, "allow_web": False})


def prepare(url: str = "", *, post: Optional[Callable] = None, marker_path: Path = MARKER) -> Dict[str, Any]:
    post = post or _http_post(url)
    teach = _research(post, USER, "rr_prepare", FACT_SENTENCE)
    recall = _research(post, USER, "rr_prepare_recall", RECALL_Q)
    pre_ok = EXPECT.lower() in (recall.get("answer") or "").lower()
    marker = {"phase": "prepared", "user": USER, "other_user": OTHER_USER,
              "fact": FACT_SENTENCE, "recall_q": RECALL_Q, "expect": EXPECT,
              "teach_status": teach.get("epistemic_status"),
              "pre_restart_recall_status": recall.get("epistemic_status"),
              "pre_restart_recall_ok": pre_ok, "ts": _now()}
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker_path.with_suffix(marker_path.suffix + ".tmp")
    tmp.write_text(json.dumps(marker, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(marker_path)
    marker["marker_written"] = marker_path.exists()
    return marker


def verify(url: str = "", *, post: Optional[Callable] = None, marker_path: Path = MARKER,
           report_path: Path = REPORT) -> Dict[str, Any]:
    if not marker_path.exists():
        return {"phase": "verify", "error": "no restart_marker.json - run --phase prepare first",
                "passed": False, "skipped": True}
    post = post or _http_post(url)
    same = _research(post, USER, "rr_verify_same", RECALL_Q)
    same_answer = (same.get("answer") or "")
    same_ok = same.get("epistemic_status") == "KNOWN" and EXPECT.lower() in same_answer.lower()
    other = _research(post, OTHER_USER, "rr_verify_other", RECALL_Q)
    leak = EXPECT.lower() in (other.get("answer") or "").lower()
    cross_ok = (not leak) and other.get("epistemic_status") in GOOD_CROSS_STATUSES
    rep = {
        "phase": "verify", "user": USER, "other_user": OTHER_USER, "recall_q": RECALL_Q,
        "same_user_status": same.get("epistemic_status"),
        "same_user_source_class": same.get("source_class"),
        "same_user_recall_ok": same_ok,
        "cross_user_status": other.get("epistemic_status"),
        "cross_user_leak": leak, "cross_user_ok": cross_ok,
        "passed": bool(same_ok and cross_ok), "ts": _now(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = report_path.with_suffix(report_path.suffix + ".tmp")
    tmp.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(report_path)
    return rep


def skip_reason() -> str:
    return ("restart-recall gate not configured: set BYON_EVAL_RESTART_PHASE=prepare (before "
            "restart) then =verify (after restart), or run scripts/live_restart_recall_eval.py "
            "--phase auto")


# -- optional self-orchestrating mode (manages the app lifecycle) -----------
def _auto(url: str) -> int:
    import os
    import subprocess

    print("[auto] phase A: prepare")
    print(json.dumps(prepare(url), indent=2, ensure_ascii=False))
    print("[auto] restarting app ...")
    # best-effort: stop listeners, relaunch run_byon.py, wait for health
    try:
        subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" /
                        "restart_app.py")], check=False, timeout=300)
    except Exception as exc:
        print(f"[auto] could not auto-restart ({exc}); restart the app manually then run "
              f"--phase verify")
        return 2
    rep = verify(url)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    return 0 if rep.get("passed") else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--phase", choices=["prepare", "verify", "auto"], required=True)
    args = ap.parse_args()
    if args.phase == "prepare":
        rep = prepare(args.url)
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0 if rep.get("pre_restart_recall_ok") else 2
    if args.phase == "verify":
        rep = verify(args.url)
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0 if rep.get("passed") else 2
    return _auto(args.url)


if __name__ == "__main__":
    sys.exit(main())
