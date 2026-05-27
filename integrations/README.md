# BYON World Connectors (v10.1 alpha)

These let real, non-technical users reach BYON - **without** any of them becoming the
epistemic authority. The trust order never changes:

```
LibreChat / OpenClaw / n8n  →  BYON Gateway / MCP  →  BYON Optimus  →  memory-service
(UI / messaging / automation)   (controlled port)     (auditor)        (FAISS + D_Cortex + real FCE-M)
                                                                              ↓
                                                                       Claude (language only)
                                                                              ↓
                                                                       BYON final audit → user
```

Hard rules for every connector:
- It forwards to BYON; it never answers from its own model/memory.
- It relays BYON's `epistemic_status` verbatim (KNOWN / UNKNOWN / DISPUTED / REFUSED / ERROR).
- It never reads another user's memory and never uses local state as truth.
- It cannot bypass BYON's final audit.

| Connector | Role | Stage | Status in v10.1 alpha |
|---|---|---|---|
| **MCP server** (`byon_mcp/`) | universal port | first | implemented + tested (handlers) |
| **LibreChat** (`librechat/`) | web UI | first | config + guide; live test needs LibreChat running |
| **OpenClaw** (`openclaw/`) | social/messaging body | second | forward-only adapter + tested policy; live test needs OpenClaw |
| **n8n** (`n8n/`) | automation muscle | third | feedback/report workflows; sensitive actions disabled |

Enable flags (env): `BYON_ENABLE_MCP`, `BYON_ENABLE_LIBRECHAT`, `BYON_ENABLE_OPENCLAW`,
`BYON_ENABLE_N8N`. In alpha, OpenClaw and n8n default OFF.
