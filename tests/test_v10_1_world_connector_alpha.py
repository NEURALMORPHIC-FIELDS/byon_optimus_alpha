"""Tests for v10.1 - BYON World Connector Alpha.

Exercises the Gateway contract, per-user namespace isolation, the MCP tool handlers,
and the OpenClaw forward-only adapter against a deterministic injected BYON backend
(a test double, not a production fallback). Live connector gates (LibreChat/OpenClaw/
n8n/orchestrator) are deferred in the runner and not asserted here.
"""
from __future__ import annotations

import importlib

import pytest

# Unit-portable: the connector layer needs FastAPI + httpx. When they are absent
# (e.g. a minimal env), skip this module rather than error at collection.
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

av = importlib.import_module("gateway.alpha_validation")


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    out = tmp_path_factory.mktemp("v10_1_out")
    return av.run_alpha_validation(outdir=out)


def test_verdict_validated(report):
    assert report["verdict"] == "V10_1_WORLD_CONNECTOR_ALPHA_VALIDATED"
    assert report["gates_passed"] == report["gates_total"]


@pytest.mark.parametrize("gate", [
    "GATEWAY_HEALTH",
    "USER_ID_REQUIRED",
    "SESSION_ID_REQUIRED",
    "NO_DIRECT_MEMORY_SERVICE_EXPOSURE",
    "RESPONSE_ALWAYS_HAS_EPISTEMIC_STATUS",
    "UNKNOWN_WHEN_UNGROUNDED",
    "BYON_FINAL_AUDIT_REQUIRED",
    "AUDIT_TRACE_CREATED_FOR_EVERY_MESSAGE",
    "PER_USER_NAMESPACE",
    "USER_A_CANNOT_READ_USER_B",
    "CROSS_USER_CONTAMINATION_ZERO",
    "MCP_CHAT_WORKS",
    "MCP_CANNOT_BYPASS_BYON_AUDIT",
    "MCP_UNKNOWN_PRESERVED",
    "MCP_AUDIT_TRACE_PRESERVED",
    "OPENCLAW_FORWARDS_ONLY",
    "N8N_FEEDBACK_WORKS",
    "KILL_SWITCH_WORKS",
    "LIBRECHAT_CONFIG_PRESENT",
])
def test_gate_passes(report, gate):
    assert report["gates"][gate] is True


def test_cross_user_contamination_is_zero(report):
    assert report["detail"]["cross_user_contamination"] == 0


def test_namespace_rejects_path_traversal():
    from gateway.namespace import UserNamespace, NamespaceIsolationError
    ns = UserNamespace("runtime/_test_users", "alice")
    with pytest.raises(NamespaceIsolationError):
        ns.path("..", "..", "etc", "passwd")


def test_unknown_answer_is_blank_and_ungrounded():
    """The epistemic invariant carried up to the connector: UNKNOWN never carries a
    fabricated answer and is never marked grounded."""
    from fastapi.testclient import TestClient
    app = av.create_app(av.GatewayConfig.from_env(), backend=av.StubBYONBackend())
    tc = TestClient(app)
    r = tc.post("/v1/chat", json={"user_id": "u", "session_id": "s",
                                  "message": "unknown oov"}).json()
    assert r["epistemic_status"] == "UNKNOWN"
    assert r["answer"] == "" and r["grounded"] is False
