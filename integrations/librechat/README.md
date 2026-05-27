# LibreChat → BYON (first web UI)

LibreChat is the first interface for non-technical alpha users. It talks to BYON
**only** through the BYON MCP server (`byon_mcp`), which routes through the Gateway.

## Wire-up

1. Start BYON memory-service + orchestrator (see repo root README) and the Gateway:
   ```bash
   python -m gateway.server         # :8090
   ```
2. Start the BYON MCP server (needs `pip install mcp`):
   ```bash
   BYON_GATEWAY_URL=http://127.0.0.1:8090 python -m byon_mcp.server
   ```
3. Point LibreChat at the MCP server using `librechat.example.yaml` +
   `byon-mcp-config.example.json` (copy, fill in, drop into your LibreChat config).

## What the user sees / does NOT see

Sees: the chat, an answer status badge (KNOWN / UNKNOWN / DISPUTED / REFUSED), a
"wrong answer" feedback button, and a "delete my memory" button.

Does **not** see: FAISS hits, FCE-M vectors, D_Cortex internals, pressure/register
state. The Gateway never exposes those.

## Live validation (deferred - needs LibreChat running)

`G17_LIBRECHAT_CONNECTS_TO_BYON_MCP`, `G18_USER_CAN_CHAT_FROM_BROWSER`,
`G19_UNKNOWN_DISPLAYED_CLEANLY`, `G20_FEEDBACK_BUTTON_WRITES_LOG`,
`G21_FORGET_BUTTON_CALLS_BYON_FORGET` are manual/integration gates: they require a
running LibreChat + Gateway and are validated during the alpha smoke test, not in
the offline suite (which only asserts the config is present).
