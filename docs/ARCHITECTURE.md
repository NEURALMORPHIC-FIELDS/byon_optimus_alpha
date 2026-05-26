# Architecture — BYON Optimus + D_Cortex (off-Colab)

```
User
  │
  ▼
BYON Optimus orchestrator (byon-orchestrator, Node/TS)
  │   Worker · Auditor · Executor(air-gapped) · trust hierarchy · intent router
  ▼
Memory-service (FastAPI, Python, :8000)  ── canonical ──────────────┐
  ├─ FAISS semantic memory (handlers.py)                            │
  ├─ verified / domain facts                                        │
  ├─ FCE-M advisory memory — REAL sealed v15.7a runtime             │   ◄ v9.9.3: external_v15_7a,
  │     (fcem_backend.py → memory_engine_runtime, external_v15_7a)  │     shim_used=false, proven
  └─ D_Cortex v9.9.x additive organ (dcortex_v99_adapter.py)  ◄── injected, additive
        ├─ morphogenetic plastic cortex (7 register organs)
        ├─ addressable persistent memory (export/import, reload)
        ├─ contradiction arbitration: provisional→committed→retrograde (v9.9.1)
        ├─ UNKNOWN-when-ungrounded decision head (v9.9.2)
        ├─ real-text assimilation + semantic grounded QA
        └─ chronodynamic internal tempo (hash-chain temporal memory)
  ▼
EPISTEMIC GATE: answer only if grounded in valid memory, else UNKNOWN
  ▼
Anthropic Claude Sonnet 4.6  (language only)
  ▼
BYON final-answer audit ──► User
```

## Integration mechanics (`orchestration/integrate.py`)

1. **verify_repo** — require a real `external/byon_optimus` checkout; fail hard otherwise.
2. **write_dcortex_injection** — copy the ported `dcortex/v99_source.py` and the
   `dcortex_v99_adapter.py` into `memory-service/`; `py_compile` both (fail before boot).
3. **patch_server_py** — idempotent injection of the four `dcortex_v99_*` actions into the
   FastAPI dispatcher (anchors verified against the real `server.py`).
4. **build** — `npm install --ignore-scripts` + `tsc` build (+ optional `vitest`).
5. **boot** — `python server.py`, poll `/health` until ready.
6. **probe** — `dcortex_v99_status`, `dcortex_v99_grounding_packet`; optional embedded audit.
7. **live E2E** — Node harness asks Claude three gated probes (known / contradiction-boundary
   / unknown) using FAISS + FCE + D_Cortex grounding, scoring BYON's epistemic discipline.

## Governing principle — the Epistemic Memory Contract (v9.9.2)

> **No model may assert from prior. An answer may be asserted only if it is anchored in valid,
> committed memory with provenance. Otherwise the answer is UNKNOWN.**

Classic (transformer/GRU) and morphogenetic faculties **coexist and meet in memory** — this is
not a contest. The decisive question is never "which model is more accurate" but "is the answer
grounded?". The contract is enforced at two agreeing layers:
- **Cortex (v9.9.2):** the decision head has an explicit UNKNOWN class; a query is answered only
  when `persistent_known` holds the key (set solely by trusted writes → provenance). No memory →
  UNKNOWN, not reconstruction from prior.
- **BYON Auditor:** FAISS-threshold empty results, the `byon_required_gate` hint, metadata-only
  evidence validators and canonical system facts — disputes and refusals are adjudicated here.

## The D_Cortex organ is *additive*, never the orchestrator

The adapter only exposes a **grounding packet** (verdict line, QA accuracies, damage metrics,
and a `byon_required_gate` hint). The cortex never overrides the trust hierarchy. With v9.9.2 the
cortex's own abstention now *agrees* with BYON's gate instead of relying on BYON to catch its
overconfidence (dev-sheet §6.2, §7.2).

## Real FCE-M v15.7a runtime (v9.9.3)

The FCE-M advisory memory is the **real sealed v15.7a consolidator**, not a stub. `fcem_backend`
loads it through `memory_engine_runtime` when `FCEM_MEMORY_ENGINE_ROOT` points at the v15.7a
`d_cortex/` package. The Colab cell embeds that package; `FSOAT_REQUIRE_EXTERNAL_FCEM_RUNTIME=true`
makes the run **fail-hard** if a shim is detected. Confirmed: `source=external_v15_7a,
shim_used=false, adapter=DCortexAdapter`, `fcem_runtime_proven=true`. Two-layer contradiction
defence: the cortex resists transient overwrite (v9.9.1), FCE-M + BYON arbitrate disputes.

## Developmental loop (`dcortex/v10_developmental_loop.py`) — **8/8**

A longitudinal cycle over the validated v9.9 primitives, run per-session on fresh checkpoints:
read/assimilate → verify → sleep-consolidate → restart/reload → QA → contradiction →
controlled forgetting → adversarial-source check. Gates (8/8): learning, reload retention,
cross-session stability, memory & addressing causal, controlled forgetting, adversarial
resilience, **contradiction_resisted** (v9.9.1). A *composition* of audited capabilities.

> Note: this in-process loop is distinct from the **v10 milestone** (Longitudinal
> Generalization & Isolation) in `dcortex/v10_milestone.py` — **validated 8/8,
> `V10_LONGITUDINAL_VALIDATED`**. The milestone adds standing gates on *real / never-audited*
> inputs with the real FCE-M v15.7a adapter mandatory (fail-hard on shim):
> `REAL_FCEM_REQUIRED`, `UNSEEN_DOMAIN_TRANSFER`, `REAL_OOV_UNKNOWN`,
> `DELAYED_RECALL_RESTART`, `CROSS_USER_ISOLATION`, `REAL_CONTRADICTION_STREAM`,
> `FCEM_ADVISORY_EFFECT`, `FALSE_ASSERTION_RATE_ZERO` (`false_assertions=0`). See `STATUS.md`.

## Failure discipline (dev-sheet §7.3)

No silent mocks. Missing real components raise with a clear message. Skipped heavy stages
are tagged `skipped: true` and never counted as passing. Every run leaves a heartbeat
ledger, a JSON results file, and (on crash) a `*_crash_report.json`.
