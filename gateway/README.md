# BYON Gateway (v10.10 alpha — Active Memory Runtime + LifeLoop v2)

A stable, controlled API port between the world and BYON, **and** the active-memory runtime.
The Gateway **never decides truth** — it routes every request through BYON (the sole epistemic
authority) and returns BYON's verdict (`KNOWN` / `PROVISIONAL` / `DISPUTED` / `UNKNOWN` /
`REFUSED` / `ERROR` / `SELF_STATE_GROUNDED` / `ACTION_DONE` / `ACTION_REQUIRED`), with the answer's
`query_class` and `source_class`.

## Surface (the only endpoints exposed)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/health` | liveness + posture flags |
| POST | `/v1/chat` | ask BYON (always returns `epistemic_status` + `audit_trace_id`) |
| POST | `/v1/research` | epistemic search loop (`action: start\|continue\|conclude`) |
| POST | `/v1/consolidate` | run the canonical FCE-M consolidation |
| POST | `/v1/feedback` | record user feedback (also a learning signal) |
| POST | `/v1/forget` | delete the calling user's memory (`confirm=true`) |
| GET  | `/v1/memory/status` | per-user namespace status + substrate (consistency, vault, tombstones, locks) |
| GET  | `/v1/audit/{trace_id}` | fetch an audit trace |
| GET  | `/v1/lifeloop` · POST `/v1/lifeloop/tick` | **LifeLoop v2** status (pressure, tasks, consistency) / tick |
| POST | `/v1/lifeloop/run-task/{id}` · `approve-web/{id}` · `cancel-task/{id}` · `mark-resolved` | task control |
| GET  | `/v1/lifeloop/task/{id}` | task evidence (result, sources) |
| GET  | `/v1/admin/metrics` | aggregate alpha counters |

Raw memory-service / D_Cortex / FCE-M / FAISS endpoints are **never** exposed. LifeLoop observes
and proposes — it **never answers the user and is never a truth authority**.

## Active Memory Runtime modules

| Module | Role |
|---|---|
| `memory_service_backend.py` | canonical REAL backend (FAISS + FCE-M + trust tiers); forbids `LocalBYONBackend` in REAL |
| `query_router.py` | intent classification + trust-tier / intent re-ranking; multilingual secret guard |
| `epistemic_search.py` | research loop + `ALLOWED_PRIMARY` answer-pool gate + canonical-override guard |
| `source_policy.py` | query-class / source-class matrix; unsafe-vault-claim detection (v10.6) |
| `self_state_provider.py` | self-introspection from runtime state (v10.4) |
| `operational_intents.py` | dynamics / proof / history / memory-action / follow-up / vault-status (v10.4) |
| `expression_learning.py` | style learned as `USER_PREFERENCE`; delivery only, never truth (v10.5) |
| `session_events.py` | literal per-session `events.jsonl` (v10.5) |
| `vault_manifest.py` · `write_lock.py` · `vault_errors.py` | chunk dedup, single-writer lock, error classes (v10.7) |
| `recent_write_buffer.py` | immediate recall before FAISS indexes; `RECENT_WRITE_BUFFER` (v10.7) |
| `consistent_client.py` · `tombstones.py` · `engine_consistency.py` | read/write consistency + tombstone overlay (v10.8/v10.10) |
| `lifeloop.py` · `pressure.py` · `research_tasks.py` | **LifeLoop v2**: pressure, internal tasks, autonomous draining (v10.9/v10.10) |
| `self_training.py` · `vault_training.py` · `fact_extractor_bridge.py` | self/vault training + canonical FactExtractor bridge |

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
python -m gateway.alpha_validation                       # 21/21 offline connector gates + report
python -m pytest -m "not live"                            # 307 non-live tests (whole runtime)
python scripts/live_byon_eval.py                          # behaves-like-a-user gates (76/76) → JSON
```
World-connector report → `runtime/v10_1_out/v10_1_world_connector_alpha_report.json`,
verdict `V10_1_WORLD_CONNECTOR_ALPHA_VALIDATED`. Active-memory live report →
`runtime/eval/live_byon_eval_report.json` (**76/76 graded, 0 fail** — Cycle 1–7 gates: source
disambiguation, secret guard, dedup/lock, read-consistency, tombstone-excluded, LifeLoop,
restart-recall). Live connector gates (LibreChat / OpenClaw / n8n / live orchestrator) are
deferred, never faked.
