# BYON Gateway (v10.1 alpha)

A stable, controlled API port between the world and BYON. The Gateway **never decides
truth** — it routes every request through BYON (the sole epistemic authority) and
returns BYON's verdict (`KNOWN` / `UNKNOWN` / `DISPUTED` / `REFUSED` / `ERROR`).

## Surface (the only endpoints exposed)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/health` | liveness + posture flags |
| POST | `/v1/chat` | ask BYON (always returns `epistemic_status` + `audit_trace_id`) |
| POST | `/v1/feedback` | record user feedback |
| POST | `/v1/forget` | delete the calling user's memory (`confirm=true`) |
| GET  | `/v1/memory/status` | per-user namespace status |
| GET  | `/v1/audit/{trace_id}` | fetch an audit trace |
| GET  | `/v1/admin/metrics` | aggregate alpha counters |

Raw memory-service / D_Cortex / FCE-M / FAISS endpoints are **never** exposed.

## Run

```bash
pip install -e .[gateway]
python -m gateway.server            # binds BYON_GATEWAY_PORT (default 8090)
```

Production uses `HttpBYONBackend` (→ `BYON_ORCHESTRATOR_URL`). If BYON is unreachable,
chat comes back as `ERROR` with **no answer** — the Gateway fabricates nothing
(dev-sheet §7.3). See `.env.example` for configuration.

## Invariants (enforced in code, not just docs)

- `user_id` + `session_id` are mandatory; memory is per-user isolated (no cross-user reads).
- No answer reaches a user unless BYON's final audit passed (`require_final_audit`).
- `UNKNOWN`-when-ungrounded is never weakened; non-`KNOWN` verdicts never carry a confident answer.
- Every message gets an audit trace. `BYON_KILL_SWITCH=true` disables external access.

## Validate

```bash
python -m gateway.alpha_validation                       # 21/21 offline gates + report
python -m pytest tests/test_v10_1_world_connector_alpha.py -v
```
Report → `runtime/v10_1_out/v10_1_world_connector_alpha_report.json`,
verdict `V10_1_WORLD_CONNECTOR_ALPHA_VALIDATED`. Live connector gates (LibreChat /
OpenClaw / n8n / live orchestrator) are deferred, never faked.
