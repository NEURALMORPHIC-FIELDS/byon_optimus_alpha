# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""MCP server wiring for BYON.

Run:  python -m byon_mcp.server     (requires `pip install mcp` and a running Gateway)

The `mcp` SDK is imported lazily inside main() so this module - and the handlers it
registers - stay importable and testable without the SDK installed.
"""
from __future__ import annotations

import os

from byon_mcp.client import GatewayClient
from byon_mcp import handlers as H


def build_client() -> GatewayClient:
    base = os.environ.get("BYON_GATEWAY_URL", "http://127.0.0.1:8090")
    return GatewayClient(base_url=base)


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - depends on optional SDK
        raise SystemExit(
            "The 'mcp' package is required to run the BYON MCP server: pip install mcp\n"
            f"(import error: {exc})")

    client = build_client()
    server = FastMCP("byon")

    @server.tool(name="byon.chat",
                 description="Ask BYON. Returns a BYON-audited answer with epistemic_status "
                             "(KNOWN/UNKNOWN/DISPUTED/REFUSED/ERROR). The ONLY user-facing tool.")
    def chat(user_id: str, session_id: str, message: str, channel: str = "api") -> dict:
        return H.byon_chat(client, user_id=user_id, session_id=session_id,
                           message=message, channel=channel)

    @server.tool(name="byon.memory_status", description="Per-user memory namespace status.")
    def memory_status(user_id: str) -> dict:
        return H.byon_memory_status(client, user_id=user_id)

    @server.tool(name="byon.feedback", description="Record user feedback about an answer.")
    def feedback(user_id: str, session_id: str, rating: str = "wrong",
                 note: str | None = None, audit_trace_id: str | None = None) -> dict:
        return H.byon_feedback(client, user_id=user_id, session_id=session_id,
                               rating=rating, note=note, audit_trace_id=audit_trace_id)

    @server.tool(name="byon.forget", description="Delete the calling user's memory (confirm=true).")
    def forget(user_id: str, confirm: bool = False) -> dict:
        return H.byon_forget(client, user_id=user_id, confirm=confirm)

    @server.tool(name="byon.audit_trace", description="Fetch a BYON audit trace by id.")
    def audit_trace(trace_id: str) -> dict:
        return H.byon_audit_trace(client, trace_id=trace_id)

    server.run()


if __name__ == "__main__":
    main()
