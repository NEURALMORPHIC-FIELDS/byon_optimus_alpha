# Changelog — BYON Optimus + D_Cortex

Progression of the off-Colab → enterprise harness. Each entry lists what changed and the
**verified verdict** (run, not claimed). Newest first.

---

## [10.1.0-alpha] — BYON World Connector Alpha · **verdict: V10_1_WORLD_CONNECTOR_ALPHA_VALIDATED (21/21 offline)**

> Not a rewrite of BYON. A **connector layer** that lets non-technical users reach BYON
> through a browser UI (and later messaging / automation), while preserving BYON as the
> *only* epistemic authority. Nothing in this layer decides truth — it forwards to BYON
> and relays BYON's verdict (KNOWN / UNKNOWN / DISPUTED / REFUSED / ERROR).

### Added (Python / FastAPI, in this repo)
- **`gateway/`** — BYON Gateway: a controlled `/v1` surface (`/chat`, `/feedback`,
  `/forget`, `/memory/status`, `/audit/{trace_id}`, `/health`, `/admin/metrics`). It never
  exposes raw memory-service / D_Cortex / FCE-M / FAISS. Mandatory `user_id`+`session_id`,
  per-user memory namespace, audit trace per message, kill switch. The Gateway never
  answers — it delegates to a `BYONBackend`; the production `HttpBYONBackend` **fails hard**
  (ERROR, no answer) if BYON is unreachable, never fabricates (dev-sheet §7.3).
- **`gateway/normalizer.py`** mechanically enforces: no answer leaves without BYON's final
  audit; non-KNOWN verdicts never carry a confident answer; UNKNOWN-when-ungrounded preserved.
- **`gateway/namespace.py`** — per-user isolated memory namespaces; path-traversal and
  cross-user access refused by construction.
- **`byon_mcp/`** — BYON MCP server (5 tools: `byon.chat/memory_status/feedback/forget/
  audit_trace`). Every tool routes through the Gateway; none queries D_Cortex/FCE-M directly
  or bypasses the final audit; only `byon.chat` is user-facing. (`mcp` SDK imported lazily.)
- **`integrations/`** — LibreChat (web UI config + alpha user guide), OpenClaw (forward-only
  adapter + agent policy), n8n (feedback + daily-report workflows; sensitive actions disabled).
- **`gateway/alpha_validation.py`** + `tests/test_v10_1_world_connector_alpha.py` — 21 offline
  gates; live connector gates (LibreChat/OpenClaw/n8n/live orchestrator) reported as
  **deferred, never faked**.

### Verified (offline, deterministic injected BYON backend)
- `verdict = V10_1_WORLD_CONNECTOR_ALPHA_VALIDATED` (**21/21**): gateway health, user_id/
  session_id required, no direct memory exposure, epistemic_status always present, UNKNOWN
  when ungrounded, **final-audit-required (un-audited KNOWN → REFUSED + blanked)**, audit trace
  per message, per-user namespace, **cross-user contamination 0**, MCP routes through gateway
  + cannot bypass audit + preserves UNKNOWN/trace, OpenClaw forward-only, n8n feedback, admin
  metrics, kill switch, LibreChat config present. Full suite pytest **38/38**.
- BYON core untouched: D_Cortex (`dcortex==10.0.0`), FCE-M core, and the v10 validation gates
  are unchanged. `FULL_LEVEL3_NOT_DECLARED` preserved.

---

## [10.0] — Longitudinal Generalization & Isolation · **verdict: V10_LONGITUDINAL_VALIDATED (8/8)**

> **Canonical formulation.** v10.0 — Longitudinal Generalization & Isolation validates the
> integrated BYON + D_Cortex + real FCE-M organism against eight standing gates designed to
> falsify audit-overfitting: mandatory real FCE-M, unseen-domain transfer, real OOV UNKNOWN
> behaviour, delayed recall after restart/interference, cross-user isolation, real-document
> contradiction streams, measurable FCE-M advisory effect, and zero false assertions on
> ungrounded queries. The milestone passes **8/8** on local CPU. It remains a controlled
> validation milestone — **not a Level-3 claim and not production-deployment proof**
> (`FULL_LEVEL3_NOT_DECLARED`).

> The next correct step after v9.9.3 was *not* more FSOAT work but a standing milestone
> that falsifies audit-overfitting (dev-sheet §10.1): every gate runs on data or keys the
> v9.9.x audits never touched, with the **real** FCE-M v15.7a consolidator mandatory.

### Added
- `dcortex/v10_milestone.py` — eight standing gates, all on never-audited inputs, built on
  the validated v9.9 primitives + the sealed v15.7a `DCortexAdapter`:
  1. **REAL_FCEM_REQUIRED** — imports the real external v15.7a adapter and proves it by
     sealed `__version__` + class identity + a live `end_episode` pipeline run; **raises
     `RealFCEMRequiredError` (fail-hard) if a shim/stub/missing engine appears** (§7.3, no
     diluted fallback).
  2. **UNSEEN_DOMAIN_TRANSFER** — domains 23/29/31 (never AG News / WikiText, never
     domain_id 5–7) learn and recall (mean post-accuracy 1.0).
  3. **REAL_OOV_UNKNOWN** — teach half the keys; the genuinely never-taught keys return
     UNKNOWN (`n_values` class), not a reconstructed prior.
  4. **DELAYED_RECALL_RESTART** — recall survives a checkpoint round-trip after interference
     from a different model on a different domain + elapsed episodes (retention 1.0).
  5. **CROSS_USER_ISOLATION** — two users with conflicting facts on the same keys; user A
     never surfaces user B's distinct values (cross-contamination 0).
  6. **REAL_CONTRADICTION_STREAM** — contradictions parsed from real English document text:
     a consolidated fact resists a transient untrusted flip, while a repeated + verified +
     re-consolidated correction still wins (v9.9.1 arbitration on real inputs).
  7. **FCEM_ADVISORY_EFFECT** — the real adapter's `LatentSignals` change measurably with
     input structure (contested slot pressure 0.60 > aligned 0.0; ADVISORY advises, OFF
     stays silent).
  8. **FALSE_ASSERTION_RATE_ZERO** — across every ungrounded query in the run
     (12 sampled), non-UNKNOWN assertions == 0.
- `tests/test_v10_milestone.py` (5 tests): document-parser regression, **fail-hard FCE-M
  gate**, sealed-adapter proof, advisory-effect, and the full 8-gate run. Full suite **15/15**.

### Fixed (genuine bugs found while building the gates)
- Query helper routed direct value queries through the relation organ whenever a relation
  existed (`rel != key`), silently returning the relation-mediated value — fixed to set the
  relation field == key for direct reads (mirrors `continual_domain_probe`).
- Single-key recall was RNG-dependent because models stayed in `train()` mode (dropout
  active); the untrained neural head could occasionally overpower the ledger's grounded
  one-hot. Fixed by running cortices in `eval()` so recall is a function of memory, not RNG.
- The real-document parser grabbed a trailing-clause word ("… in Calder this year." → "year")
  instead of the place name; fixed to extract the place introduced by a locative preposition.

### Validation profiles (dev-sheet §7.3 — real FCE-M is skippable only in unit-portable)
- **Unit-portable** (default): engine-dependent tests `skip` when the v15.7a engine is not
  locally resolvable, so the fast suite stays green offline.
- **Release validation**: `BYON_VALIDATE_REAL_FCEM=true python -m pytest
  tests/test_v10_milestone.py -m slow -v` — a missing real engine is a **hard FAIL, never a
  skip**. REAL_FCEM_REQUIRED is mandatory in validation.

### Verified (local CPU, fast profile, real v15.7a engine resolved)
- `verdict = V10_LONGITUDINAL_VALIDATED` (**8/8**), `false_assertions=0`,
  `adapter=DCortexAdapter`, `version=0.1.0-extracted-from-v15.7a-sealed-2026-04-26`.
- Fail-hard re-confirmed: a bogus `FCEM_MEMORY_ENGINE_ROOT` raises `RealFCEMRequiredError`
  instead of degrading to a stub; under `BYON_VALIDATE_REAL_FCEM=true` the test suite FAILs
  rather than skips. `FULL_LEVEL3_NOT_DECLARED` preserved — this is a controlled validation
  milestone, not a Level-3 claim and not production-deployment proof.

> Distinct from the in-process `v10_developmental_loop.py` (8/8 capability composition);
> the milestone adds *standing generalization + isolation* gates on real / unseen inputs.

---

## [9.9.3] — Real FCE-M Runtime Proof · **verdict: PASS**

> The previous FSOAT limitation is closed: the run no longer uses the vendored minimal shim.
> FSOAT now requires and confirms external FCE-M v15.7a runtime, with `fce_state`,
> `fce_advisory` and synthetic receipt assimilation passing under strict mode. This validates
> real FCE-M activation inside the full BYON + D_Cortex organism, while preserving
> `FULL_LEVEL3_NOT_DECLARED`.

### Root cause
`fcem_backend`'s `memory_engine_runtime._DEFAULT_ROOT` is hard-pinned to a local path that
exists on the developer machine but **not on Colab** → on Colab it silently fell back to the
vendored `_MinimalDCortexAdapter` shim (`fcem_runtime_proven=false`).

### Fix (additive, no science changed)
- The real sealed **v15.7a `d_cortex` consolidator** (4 pure-stdlib files: `__init__`,
  `v15_7a_core`, `adapter`, `receptor`) is **embedded** in the full-organism Colab cell and
  written to `/content/fcem_v15_7a_engine/d_cortex` at runtime.
- `FCEM_MEMORY_ENGINE_ROOT` is set to that engine; `FSOAT_REQUIRE_EXTERNAL_FCEM_RUNTIME=true`
  makes FSOAT **fail-hard** if a shim is detected (no diluted fallback, dev-sheet §7.3).
- `orchestration/integrate.py` resolves and exports the same env for local runs.

### Verified
- **Local**: memory-service `/health` → `runtime_source=external_v15_7a, shim_used=false,
  adapter_class=DCortexAdapter, available=true`.
- **Colab (run 3)**: `FCE-M runtime: source=external_v15_7a shim_used=false adapter=DCortexAdapter`
  · `external FCE-M v15.7a runtime CONFIRMED` · `real-fcem-runtime-proof: fcem_runtime_proven=true`,
  inside a full run with D_Cortex **87/87**, FSOAT **11/11** (`FSOAT_ACTIVATION_VERIFIED |
  FULL_LEVEL3_NOT_DECLARED`), live Claude E2E **3/3**, `success=True`.

---

## [9.9.2] — Epistemic Memory Contract (UNKNOWN-when-ungrounded) · **verdict: PASS (87/87 GPU)**

Governing principle, above every module (LLM · D_Cortex · FAISS · FCE-M · BYON Auditor):
> **No model may assert from prior. An answer may be asserted only if it is anchored in valid,
> committed memory with provenance. Otherwise the answer is UNKNOWN.** Classic and morphogenetic
> faculties **coexist and meet in memory** — not a contest.

### Added
- **UNKNOWN class** in the cortex decision head (`n_values + 1`). A query/archive-query is
  answered only when `persistent_known` holds the key (set only by trusted writes → carries
  provenance); otherwise the cortex emits **UNKNOWN** instead of reconstructing from prior.
- OOV test (`test_epistemic_contract_unknown_on_empty_memory`).
- **Evaluation reframe**: the five `morpho_beats_*control*` gates → complementarity + epistemic
  criteria: `best_faculty_strong_multi`, `classic_faculty_competitive`,
  `morpho_persistent_memory_advantage`, **`unknown_when_ungrounded`** (supreme gate),
  `morpho_plasticity_advantage_over_nonplastic`.

### Verified
- **Full GPU (Colab T4)**: D_Cortex **`CHRONODYNAMIC_SEMANTIC_GROUNDED_CORTEX_VALIDATED_WEAK —
  87/87`** (zero fails) on real corpus (AG News + WikiText, 48 docs, tokenizer 50000/50000,
  reader loss 9.76→1.58, closed-book QA 1.0). `no_answer` **0.567 → 1.0** vs the pre-v9.9.2 run
  (81/87). Same run: vitest 697/697, FSOAT 11/11, live Claude E2E 3/3.
- **Local CPU**: synthetic core unchanged (59/59), v10 loop **8/8**, pytest **10/10**;
  anti-memorization strengthened (disabled-memory damage → 1.0).

---

## [9.9.1] — Contradiction-resistant addressable memory · **verdict: PASS**

Sleep-gated commitment & arbitration (mirrors the sealed v15.7a consolidator, M=2). A value
becomes *committed* only after a sleep consolidation; a conflicting re-ingest accumulates as a
*challenger* and can only replace the committed value at a later sleep. Unknown/uncommitted keys
keep the original last-write-wins, so no prior audit changes; genuine repeated+re-consolidated
corrections still update.

### Verified
- contradiction-boundary retention **0.0 → 1.0** for a transient re-ingested contradiction.
- v10 developmental loop **7/7 → 8/8**; learning, reload, forgetting, adversarial resilience
  unchanged. Two-layer defence: cortex resists transient overwrite; the BYON Auditor adjudicates
  disputes at answer time (confirmed by the live boundary probe).

---

## [9.9.0] — off-Colab enterprise harness · **verdict: PASS (CPU 59/59 exercised)**

Turned the v9.9 monolithic Google-Colab `.txt` into a maintainable, testable, locally-runnable
product. BYON Optimus stays the orchestrator/epistemic auditor; D_Cortex is an additive
morphogenetic memory organ.

### Added
- `dcortex/v99_source.py` (ported cortex), `orchestration/integrate.py` (local full-organism
  runner with a unit-tested idempotent `apply_server_patch`), `orchestration/dcortex_v99_adapter.py`,
  `orchestration/byon-dcortex-v99-live-e2e.mjs`, `dcortex/v10_developmental_loop.py`, `tests/`,
  CI, README, `docs/ARCHITECTURE.md`, `run.ps1`.

### Fixed (genuine bugs found while porting)
- `fast_run` env was ignored (hard-pinned False); adapter `grounding_packet` crashed on a string
  `verdict`; E2E shebang on line 2 (ESM SyntaxError); brittle `unknown` scorer; Colab/Drive +
  Windows long-path coupling.

### Verified (local CPU)
- Off-Colab D_Cortex audit: **59/59 exercised criteria pass** (real BYON level3 import,
  morphogenetic plasticity causal, register specialization, persistent reload/retention, sleep
  consolidation, addressable key damage, anti-leakage, chronodynamic hash-chain). Real-text /
  semantic-QA stage skipped on CPU (GPU target) → reported `skipped:true`, never passed.
- Full-organism memory-service boots locally with the D_Cortex organ injected; live Claude
  E2E **3/3**.
