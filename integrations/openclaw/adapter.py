"""OpenClaw → BYON adapter (forward-only).

OpenClaw is the social/messaging body (WhatsApp, Telegram, Slack, …). It is NOT an
epistemic authority. This adapter enforces that by construction: it has exactly one
behaviour — forward the inbound message to BYON (via the Gateway/MCP) and return
BYON's audited verdict verbatim. There is no local-answer path, no local memory used
as truth, and no rewriting of BYON's epistemic status.
"""
from __future__ import annotations

from typing import Any, Dict

from byon_mcp.client import GatewayClient
from byon_mcp import handlers as H


def handle_openclaw_message(client: GatewayClient, *, user_id: str, session_id: str,
                            text: str, channel: str = "openclaw") -> Dict[str, Any]:
    """Forward an OpenClaw inbound message to BYON and return BYON's verdict as-is.

    The returned dict is exactly what BYON decided; the adapter adds nothing of its
    own and downgrades nothing. If BYON says UNKNOWN/DISPUTED/REFUSED, that is what
    the messaging channel relays."""
    if not user_id or not session_id:
        raise ValueError("OpenClaw adapter requires user_id and session_id (no anonymous access)")
    result = H.byon_chat(client, user_id=user_id, session_id=session_id,
                         message=text, channel=channel)
    # Forward-only invariant: never substitute a local answer for a non-KNOWN verdict.
    return {
        "reply": result["answer"],
        "epistemic_status": result["epistemic_status"],
        "audit_trace_id": result.get("audit_trace_id"),
        "forwarded_to_byon": True,
        "answered_locally": False,
    }
