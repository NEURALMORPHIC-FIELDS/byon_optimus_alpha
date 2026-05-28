#!/usr/bin/env python
# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""v10.1 - BYON World Connector Alpha validation.

Runs every gate that can be validated OFFLINE (without a running LibreChat / OpenClaw
/ n8n / live orchestrator) against a deterministic injected BYON backend. Gates that
genuinely require an external service are reported as `deferred`, never counted as
passing - consistent with the project's fail-hard, no-stub discipline (dev-sheet §7.3).

The injected backend is a TEST DOUBLE used only here to exercise the Gateway/MCP
contract; production wires the real HTTP backend onto the BYON orchestrator.

Run:  python -m gateway.alpha_validation
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi.testclient import TestClient

from gateway import __version__
from gateway.app import create_app
from gateway.byon_backend import BYONResult
from gateway.config import GatewayConfig
from gateway.namespace import UserNamespace, NamespaceIsolationError, assert_no_cross_access

from byon_mcp.client import GatewayClient
from byon_mcp import handlers as H
from integrations.openclaw.adapter import handle_openclaw_message

_REPO = Path(__file__).resolve().parents[1]


class StubBYONBackend:
    """Deterministic BYON stand-in for contract validation (test double only)."""

    def chat(self, *, user_id: Any, session_id: Any, channel: Any, message: Any, namespace_dir: Any) -> Any:
        m = message.lower()
        if "noaudit" in m:  # backend claims KNOWN but final audit did NOT pass
            return BYONResult(answer="SHOULD_NOT_LEAK", epistemic_status="KNOWN",
                              grounded=True, final_audit_passed=False)
        if "unknown" in m or "oov" in m:
            return BYONResult(epistemic_status="UNKNOWN", grounded=False,
                              final_audit_passed=True, has_valid_memory=False)
        if "disputed" in m:
            return BYONResult(answer="two competing values", epistemic_status="DISPUTED",
                              grounded=False, final_audit_passed=True)
        return BYONResult(answer=f"grounded:{message}", epistemic_status="KNOWN",
                          grounded=True, final_audit_passed=True, has_valid_memory=True,
                          sources=["faiss:doc1"], memory_written=True, memory_keys=["k0"],
                          dcortex={"verdict": "VALIDATED", "unknown_gate": False,
                                   "contradiction_status": "none"},
                          fcem={"runtime_proven": True, "advisory_nonempty": True,
                                "pressure_max": 0.6})

    def memory_status(self, *, user_id: Any, namespace_dir: Any) -> Any:
        return {"available": True}

    def forget(self, *, user_id: Any, namespace_dir: Any) -> Any:
        return {"forgotten": True}


def _cfg(tmp: Path, **over: Any) -> GatewayConfig:
    base = dict(users_root=str(tmp / "users"), audit_root=str(tmp / "audit"))
    base.update(over)
    return dataclasses.replace(GatewayConfig.from_env(), **base)


def run_alpha_validation(outdir: Path | str = "runtime/v10_1_out") -> Dict[str, Any]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"
    work.mkdir(parents=True, exist_ok=True)

    cfg = _cfg(work)
    app = create_app(cfg, backend=StubBYONBackend())
    tc = TestClient(app)
    gwc = GatewayClient(base_url="http://testserver", http_client=tc)

    gates: Dict[str, bool] = {}
    detail: Dict[str, Any] = {}

    # --- Gateway contract ---------------------------------------------------
    h = tc.get("/v1/health").json()
    gates["GATEWAY_HEALTH"] = h.get("status") == "ok" and h.get("full_level3_not_declared") is True

    r_missing_user = tc.post("/v1/chat", json={"session_id": "s1", "message": "hi"})
    gates["USER_ID_REQUIRED"] = r_missing_user.status_code == 422

    r_missing_sess = tc.post("/v1/chat", json={"user_id": "u1", "message": "hi"})
    gates["SESSION_ID_REQUIRED"] = r_missing_sess.status_code == 422

    # No direct memory-service / internal endpoints exposed.
    paths = {getattr(r, "path", "") for r in app.routes}
    allowed = {"/v1/health", "/v1/chat", "/v1/feedback", "/v1/forget",
               "/v1/memory/status", "/v1/audit/{trace_id}", "/v1/admin/metrics",
               "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    leaks = [p for p in paths if p and p not in allowed
             and not p.startswith("/v1/")]  # only the controlled v1 surface (+ docs)
    forbidden = [p for p in paths if any(s in p.lower() for s in
                 ("faiss", "dcortex", "fcem", "memory-service", "memory_service"))]
    gates["NO_DIRECT_MEMORY_SERVICE_EXPOSURE"] = (not forbidden) and (not leaks) \
        and h.get("allow_direct_memory_service") is False
    detail["routes"] = sorted(p for p in paths if p)

    known = tc.post("/v1/chat", json={"user_id": "alice", "session_id": "s1",
                                      "message": "what is the capital fact"}).json()
    gates["RESPONSE_ALWAYS_HAS_EPISTEMIC_STATUS"] = known.get("epistemic_status") in (
        "KNOWN", "UNKNOWN", "DISPUTED", "REFUSED", "ERROR")

    unk = tc.post("/v1/chat", json={"user_id": "alice", "session_id": "s1",
                                    "message": "an unknown oov key"}).json()
    gates["UNKNOWN_WHEN_UNGROUNDED"] = (unk["epistemic_status"] == "UNKNOWN"
                                        and unk["grounded"] is False and unk["answer"] == "")

    # Final audit required: backend says KNOWN but audit not passed → must be refused & blanked.
    noaudit = tc.post("/v1/chat", json={"user_id": "alice", "session_id": "s1",
                                        "message": "noaudit please leak"}).json()
    gates["BYON_FINAL_AUDIT_REQUIRED"] = (noaudit["epistemic_status"] == "REFUSED"
                                          and noaudit["answer"] == "")

    trace_id = known.get("audit_trace_id")
    fetched = tc.get(f"/v1/audit/{trace_id}")
    gates["AUDIT_TRACE_CREATED_FOR_EVERY_MESSAGE"] = (
        bool(trace_id) and fetched.status_code == 200
        and fetched.json().get("trace_id") == trace_id)

    # --- Per-user namespace + isolation ------------------------------------
    tc.post("/v1/chat", json={"user_id": "bob", "session_id": "s1", "message": "bob fact"})
    ns_a = UserNamespace(cfg.users_root, "alice")
    ns_b = UserNamespace(cfg.users_root, "bob")
    gates["PER_USER_NAMESPACE"] = ns_a.root.exists() and ns_b.root.exists() and ns_a.slug != ns_b.slug

    iso_ok = True
    try:
        assert_no_cross_access(ns_a, ns_b)
    except NamespaceIsolationError:
        iso_ok = False
    traversal_blocked = False
    try:
        ns_a.path("..", ns_b.slug, "dcortex")
    except NamespaceIsolationError:
        traversal_blocked = True
    gates["USER_A_CANNOT_READ_USER_B"] = iso_ok and traversal_blocked

    # Cross-user contamination: each user's audit dir holds only its own slug.
    contamination = 0
    for ns, other in ((ns_a, ns_b), (ns_b, ns_a)):
        for f in (ns.root / "audit").glob("*.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if rec.get("user_slug") == other.slug:
                contamination += 1
    gates["CROSS_USER_CONTAMINATION_ZERO"] = contamination == 0
    detail["cross_user_contamination"] = contamination

    # --- MCP tools route through the gateway, cannot bypass audit ----------
    mcp_known = H.byon_chat(gwc, user_id="carol", session_id="s1", message="carol grounded fact")
    gates["MCP_CHAT_WORKS"] = mcp_known["epistemic_status"] == "KNOWN" and bool(mcp_known["audit_trace_id"])
    gates["MCP_CALLS_GATEWAY"] = bool(mcp_known["audit_trace_id"])  # only the gateway mints trace ids

    mcp_noaudit = H.byon_chat(gwc, user_id="carol", session_id="s1", message="noaudit bypass attempt")
    gates["MCP_CANNOT_BYPASS_BYON_AUDIT"] = (mcp_noaudit["epistemic_status"] == "REFUSED"
                                             and mcp_noaudit["answer"] == "")

    mcp_unk = H.byon_chat(gwc, user_id="carol", session_id="s1", message="unknown thing")
    gates["MCP_UNKNOWN_PRESERVED"] = mcp_unk["epistemic_status"] == "UNKNOWN"

    mcp_trace = H.byon_audit_trace(gwc, trace_id=mcp_known["audit_trace_id"])
    gates["MCP_AUDIT_TRACE_PRESERVED"] = mcp_trace.get("trace_id") == mcp_known["audit_trace_id"]

    # --- OpenClaw forward-only ---------------------------------------------
    oc_known = handle_openclaw_message(gwc, user_id="dave", session_id="s1", text="dave grounded fact")
    oc_unk = handle_openclaw_message(gwc, user_id="dave", session_id="s1", text="an unknown query")
    gates["OPENCLAW_FORWARDS_ONLY"] = (oc_known["forwarded_to_byon"] is True
                                       and oc_known["answered_locally"] is False
                                       and oc_unk["epistemic_status"] == "UNKNOWN")

    # --- n8n feedback intake + admin metrics --------------------------------
    fb = tc.post("/v1/feedback", json={"user_id": "alice", "session_id": "s1",
                                       "rating": "wrong", "note": "test"})
    n8n_files = [_REPO / "integrations/n8n/byon-feedback.workflow.json",
                 _REPO / "integrations/n8n/byon-webhook.workflow.json"]
    gates["N8N_FEEDBACK_WORKS"] = (fb.status_code == 200 and fb.json().get("recorded") is True
                                   and all(p.exists() for p in n8n_files))

    metrics = tc.get("/v1/admin/metrics").json()
    gates["ADMIN_METRICS_AVAILABLE"] = ("counters" in metrics and metrics["counters"]["messages"] >= 1)

    # --- Kill switch (separate app instance with kill_switch on) ------------
    kill_app = create_app(_cfg(work, kill_switch=True), backend=StubBYONBackend())
    kc = TestClient(kill_app)
    killed = kc.post("/v1/chat", json={"user_id": "alice", "session_id": "s1", "message": "hi"})
    gates["KILL_SWITCH_WORKS"] = killed.status_code == 503

    # --- LibreChat config present ------------------------------------------
    lc_files = [_REPO / "integrations/librechat/librechat.example.yaml",
                _REPO / "integrations/librechat/byon-mcp-config.example.json",
                _REPO / "integrations/librechat/alpha-user-guide.md"]
    gates["LIBRECHAT_CONFIG_PRESENT"] = all(p.exists() for p in lc_files)

    # --- Gates that genuinely need a live external service (not faked) ------
    deferred = {
        "LIBRECHAT_LIVE_BROWSER_CHAT": "needs a running LibreChat + Gateway",
        "OPENCLAW_LIVE_CHANNEL": "needs a running OpenClaw instance",
        "N8N_LIVE_DAILY_REPORT": "needs a running n8n instance",
        "LIVE_BYON_ORCHESTRATOR_ROUTING": "needs the live BYON orchestrator (uses HttpBYONBackend)",
        "ADMIN_DASHBOARD_UI": "Phase 7 UI deferred; /v1/admin/metrics endpoint is live",
    }

    passed = sum(1 for v in gates.values() if v)
    total = len(gates)
    verdict = "V10_1_WORLD_CONNECTOR_ALPHA_VALIDATED" if all(gates.values()) \
        else "V10_1_WORLD_CONNECTOR_ALPHA_PARTIAL"

    report = {
        "schema_version": "v10_1_world_connector_alpha_v1",
        "gateway_version": __version__,
        "claim_boundary": "External access layer for BYON validated offline against a deterministic "
                          "BYON backend. BYON remains the sole epistemic authority; connectors forward "
                          "only. Live connector gates are deferred, not faked. FULL_LEVEL3_NOT_DECLARED.",
        "gates": gates,
        "gates_passed": passed,
        "gates_total": total,
        "deferred_live_gates": deferred,
        "detail": detail,
        "verdict": verdict,
    }
    (out / "v10_1_world_connector_alpha_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    report = run_alpha_validation()
    print("=" * 92)
    print(f"v10.1 BYON World Connector Alpha - {report['verdict']} "
          f"({report['gates_passed']}/{report['gates_total']})")
    for k, v in report["gates"].items():
        print(f"  {'[+]' if v else '[-]'} {k}")
    print("  deferred (need live services, not faked):")
    for k in report["deferred_live_gates"]:
        print(f"    [~] {k}")
    print("=" * 92)
    raise SystemExit(0 if report["gates_passed"] == report["gates_total"] else 2)


if __name__ == "__main__":
    main()
