"""BYON MCP Server — the universal port onto BYON.

LibreChat, OpenClaw, n8n, or any MCP-speaking client call the same five tools, and
every one of them routes through the BYON Gateway. No MCP tool queries D_Cortex or
FCE-M directly, and no tool can bypass BYON's final audit. Only `byon.chat` returns
a final user-facing answer.

The package is intentionally NOT named `mcp` so it never shadows the `mcp` PyPI SDK.
The SDK is imported lazily in `server.py`, so handlers/clients are usable (and
testable) without it installed.
"""
from __future__ import annotations

__version__ = "10.1.0-alpha"

__all__ = ["__version__"]
