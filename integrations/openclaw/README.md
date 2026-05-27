# OpenClaw → BYON (second-stage messaging connector)

OpenClaw gives BYON a social body (WhatsApp, Telegram, Slack, …). It is the **mouth
and ears, never the mind**: it forwards every message to BYON and relays BYON's
audited verdict. Default `BYON_ENABLE_OPENCLAW=false` in alpha.

- Forward-only adapter: [`adapter.py`](adapter.py) - `handle_openclaw_message(...)`
  calls `byon_mcp` → Gateway → BYON, returns BYON's answer + `epistemic_status` as-is.
- Agent instructions: [`byon-openclaw-agent.md`](byon-openclaw-agent.md).
- Example config: [`openclaw-config.example.json`](openclaw-config.example.json).

Gates `G22..G26` (forwards all messages, no direct answer, preserves user_id, preserves
UNKNOWN, no local memory as authority): the adapter's policy is unit-tested in the
offline suite; the *live* channel test requires a running OpenClaw instance.
