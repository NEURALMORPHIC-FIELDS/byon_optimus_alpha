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

## Active Memory Runtime (v10.4–v10.6)

The one-command app (`run_byon.py`) adds a runtime layer **on top of** the canonical backend —
it composes the existing pieces, it does not replace any of them.

```
User ─► Gateway /v1 ─► MemoryServiceBackend ─► EpistemicSearch.run()
                                                  │
   classify_intent (query_router)                 │  intent + query_class (source_policy)
   ├─ SECRET ───────────────► REFUSED/UNKNOWN (no Claude, no web; multilingual guard)
   ├─ SELF_* (capability/memory/limitation/…) ─► SelfStateProvider  → SELF_STATE_GROUNDED
   ├─ operational (dynamics/proof/history/action/follow-up/vault-status) ─► OperationalIntents
   ├─ SELF_ARCHITECTURE ─► canonical relation/repo facts (+ canonical-override guard → DISPUTED)
   └─ general ─► memory (trust-tier + intent re-rank) ─► ALLOWED_PRIMARY answer-pool gate
                  ─► Claude hypothesis (not authority) ─► web (opt-in) ─► synthesis ─► verdict
                                                  │
   ExpressionLearning.apply()  ◄── delivery re-phrased per USER_PREFERENCE (never alters truth)
                                                  ▼
   SessionEvents.log_turn()  +  BYON final audit  ─► User  (status + source_class + audit trace)
```

### Source-class disambiguation (`source_policy.py`)
A fact's **origin** decides what it may ground. Each answer carries a `query_class`
(system / user_vault / objective / user_personal / secret / self_state / operational) and a
`source_class` (SYSTEM_CANONICAL · VERIFIED_PROJECT_FACT · DOMAIN_VERIFIED · USER_MEMORY_GROUNDED ·
EXTRACTED_USER_CLAIM · PROVISIONAL_WEB · DISPUTED_OR_UNSAFE · UNKNOWN). `ALLOWED_PRIMARY` blocks
source bleed **both ways**: a personal vault note never grounds a system/objective question
(framed "În notele tale apare…"), and a system/project fact never grounds a personal "my X" /
objective-world question. A vault note contradicting a fixed canonical constraint (Level 3,
FCE-M-approves, Auditor-bypass, consciousness) is detected (raw-hit scan + targeted vault probe)
and returned **DISPUTED** with the canonical correction — never echoed.

### Persistence & evaluation
Per-user isolation maps `user_id → memory-service thread_id` (system facts are thread_id=None,
visible to all). Recall **survives restart** (FAISS persisted) — proven by the two-phase
`live_restart_recall_eval.py` gate (same-user KNOWN post-restart, other-user no leak). The whole
runtime is exercised by `scripts/live_byon_eval.py` (behaves-like-a-user gates → JSON report with
source-class / vault-misuse / cross-user-leak / restart roll-ups).

## Hardened substrate (v10.7–v10.8)

The memory substrate underneath the runtime is hardened so autonomy is not built over a flaky
index — all at the canonical access boundary (the sealed memory-service is never rewritten):

- **Content-addressed dedup** (`vault_manifest.py`): each chunk has a stable `source_id` +
  `chunk_sha256`; a re-index skips unchanged chunks (and bootstraps the dedup set from facts
  already in memory). **Single-writer lock** (`write_lock.py`) + **process guard**
  (`byon_process_guard.py`) prevent concurrent/orphan writers from churning the index.
- **Read/write consistency** (`engine_consistency.py`, `consistent_client.py`): every access
  shares an engine read/write coordination lock — a writer marks a write batch (begin/commit), a
  reader **waits (bounded)** for commit before reading, so no reader observes a partial
  FAISS/metadata state. Signal: `read_consistency_mode=in_engine_rw_lock`, `snapshot_version`,
  `last_write_batch_id`, `last_consistent_read_ts`; the Cycle-5 snapshot+retry is the fallback.
- **Tombstone overlay** (`tombstones.py`): a fact is retired by tombstone (never physical delete) —
  excluded from normal search, returned only with `include_tombstoned`, audited and reversible;
  `compact_vault_memory.py` retires duplicate vault facts (dry-run default; never canonical).
- **Recent-write buffer** (`recent_write_buffer.py`): a just-taught personal fact is recallable
  before FAISS indexes it, marked `source_class=RECENT_WRITE_BUFFER`.

## LifeLoop v2 — internal circulation (v10.9–v10.10)

`lifeloop.py` + `pressure.py` + `research_tasks.py`. It **observes and proposes, never answers the
user and never decides truth** (`is_truth_authority=false`, `answers_user_directly=false`):

```
events.jsonl ─► pressure model (per topic, time-decayed) ─► recommended_action
     │                                          │
     │                                          ├─ repeated UNRESOLVED ─► internal ResearchTask
     │                                          │     (memory/vault/self-state auto on tick;
     │                                          │      WEB needs user permission; secrets never)
     ▼                                          ▼
 tick(): pressure/disputed/correction ─► canonical FCE-M consolidation (no manual promotion)
         drain memory-only tasks ─► canonical research loop (web off, audit on)
                                    ─► result stored as CANDIDATE (never truth) + task_results.jsonl
         write self_state_snapshots.jsonl (known/unknown/disputed, pressure, tasks, vault facts)
```

Pressure: UNKNOWN +1 / repeated +2 / PROVISIONAL +0.5 / DISPUTED +2 / neg-feedback +3 /
correction +2 / accepted −1 / consolidation −2; time decay; success −1 / fail +1 / repeated fail →
blocked (asks the user). `priority = pressure + unresolved + 2·disputed − success`. Secrets are
redacted in events and never create or run a task. BYON answers "ce te preocupă intern? / ce
presiuni? / ce contradicții? / ce sarcini interne?" from these snapshots + the task queue.

## Failure discipline (dev-sheet §7.3)

No silent mocks. Missing real components raise with a clear message. Skipped heavy stages
are tagged `skipped: true` and never counted as passing. Every run leaves a heartbeat
ledger, a JSON results file, and (on crash) a `*_crash_report.json`.
