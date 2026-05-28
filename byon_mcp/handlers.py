# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""MCP tool handlers.

Each handler is a plain function so it can be unit-tested without an MCP transport
or the `mcp` SDK installed. `server.py` registers these as MCP tools.

Policy enforced here:
- Only `byon_chat` returns a final user-facing answer.
- Every handler calls the BYON Gateway (via GatewayClient) - none touches D_Cortex
  or FCE-M directly, and none can bypass BYON's final audit (the Gateway enforces
  that on the way out).
- The handler echoes BYON's `epistemic_status` and `audit_trace_id` unchanged; it
  never upgrades UNKNOWN/DISPUTED/REFUSED into a confident answer.
"""
from __future__ import annotations

from typing import Any, Dict

from byon_mcp.client import GatewayClient

TOOL_NAMES = ["byon.chat", "byon.memory_status", "byon.feedback", "byon.forget", "byon.audit_trace"]
# Only this tool is allowed to surface a final answer to the end user.
USER_FACING_TOOLS = {"byon.chat"}


def byon_chat(client: GatewayClient, *, user_id: str, session_id: str,
              message: str, channel: str = "api") -> Dict[str, Any]:
    resp = client.chat({"user_id": user_id, "session_id": session_id,
                         "channel": channel, "message": message})
    # Pass BYON's verdict through verbatim - never rewrite the epistemic status.
    return {
        "answer": resp.get("answer", ""),
        "epistemic_status": resp.get("epistemic_status", "ERROR"),
        "grounded": resp.get("grounded", False),
        "audit_trace_id": resp.get("audit_trace_id"),
        "grounding_summary": resp.get("grounding_summary"),
        "memory_summary": resp.get("memory_summary"),
        "dcortex_summary": resp.get("dcortex_summary"),
        "fcem_summary": resp.get("fcem_summary"),
    }


def byon_memory_status(client: GatewayClient, *, user_id: str) -> Dict[str, Any]:
    return client.memory_status(user_id)


def byon_feedback(client: GatewayClient, *, user_id: str, session_id: str,
                  rating: str = "wrong", note: str | None = None,
                  audit_trace_id: str | None = None) -> Dict[str, Any]:
    return client.feedback({"user_id": user_id, "session_id": session_id,
                            "rating": rating, "note": note,
                            "audit_trace_id": audit_trace_id})


def byon_forget(client: GatewayClient, *, user_id: str, confirm: bool = False) -> Dict[str, Any]:
    return client.forget({"user_id": user_id, "confirm": confirm})


def byon_audit_trace(client: GatewayClient, *, trace_id: str) -> Dict[str, Any]:
    return client.audit_trace(trace_id)
