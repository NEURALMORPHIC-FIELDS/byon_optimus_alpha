# Delivery status — BYON Optimus + D_Cortex

Last update: 2026-05-26 · Targets: local Windows (CPU torch, Node 24) + Colab GPU (T4) ·
Live model: `claude-sonnet-4-6` · Official orchestrator: `byon_optimus@main` (`3b94773`),
real level3 modules `research/level-3-natural-omega` (`ef689e9`).

This file states only what was **run and verified**, organised by the version progression.

---

## Version progression (each PASS is a real run, not a claim)

| Version | What it established | Verdict |
|---|---|---|
| **v9.9.0** | Off-Colab port + local full-organism harness | PASS — CPU **59/59** exercised; live E2E 3/3 |
| **v9.9.1** | Contradiction-resistant addressable memory (sleep-gated arbitration) | PASS — contradiction retention 0→1; v10 **7/7** |
| **v9.9.2** | Epistemic Memory Contract (UNKNOWN-when-ungrounded) + coexistence reframe | PASS — GPU **87/87**; no_answer 0.567→1.0; v10 **8/8** |
| **v9.9.3** | **Real FCE-M v15.7a runtime proof** (no shim, strict mode) | **PASS** — `fcem_runtime_proven=true` |
| **v10.0** | **Longitudinal Generalization & Isolation** (8 standing gates, real FCE-M mandatory) | **PASS** — `V10_LONGITUDINAL_VALIDATED` 8/8, `false_assertions=0` |
| **v10.1-alpha** | **BYON World Connector Alpha** (Gateway + MCP + per-user namespace + connectors) | **PASS** — `V10_1_WORLD_CONNECTOR_ALPHA_VALIDATED` 21/21 offline; live connector gates deferred |
| **v10.2–10.3-alpha** | Epistemic Search + Continuous Learning + **Active Memory Core** (canonical-only; retrieval re-ranking by trust tier + intent) | **PASS** — 113/113 non-live; live re-verified on the restarted stack |
| **v10.4-alpha** | Self-introspection (`SelfStateProvider`) + operational intents + self/vault training + **BYONLifeLoop v1** | **PASS** — answered from runtime state, never vault/slogan |
| **v10.5-alpha** | Expression/style learning + per-session event stream + **live evaluation harness** | **PASS** — 178 non-live; live harness 25/25 graded (restart-recall documented skip) |
| **v10.6-alpha** | **Source-class disambiguation + two-phase restart-recall + vault-report coherence** | **PASS** — **196 non-live; live harness 35/35 graded, 0 fail, 0 skip; restart recall passes** |

---

## Final validated state

### Colab GPU (full organism, live, run 3) — comprehensive
- **D_Cortex audit**: `CHRONODYNAMIC_SEMANTIC_GROUNDED_CORTEX_VALIDATED_WEAK` — **87/87**, 0 fails.
  Real corpus (AG News + WikiText, 48 docs), tokenizer **50000/50000**, reader loss 9.76→1.58,
  closed-book QA **1.0**, no_answer **1.0**. ~64 min on T4.
- **FCE-M runtime**: `source=external_v15_7a, shim_used=false, adapter=DCortexAdapter`;
  `FSOAT_REQUIRE_EXTERNAL_FCEM_RUNTIME=true`; **`fcem_runtime_proven=true`**. `fce_state`,
  `fce_advisory`, synthetic receipt assimilation all pass under strict mode.
- **FSOAT**: 11/11 organs active, verdict `FSOAT_ACTIVATION_VERIFIED | FULL_LEVEL3_NOT_DECLARED`.
  Worker→Auditor→Executor loop with live Claude, Ed25519-signed ExecutionOrders, verified receipts.
- **Live Claude E2E**: **3/3** (known = Level 2 · boundary = rejects Level-3 · unknown = refuses).
- **Orchestrator tests (vitest)**: **697/697** (31 files); `tsc` build clean.
- Full-organism `success = True`.

### Local Windows CPU
- Off-Colab D_Cortex audit: **59/59** exercised criteria (real-text stage is the GPU target).
- v10 developmental loop **8/8**; **v10 milestone `V10_LONGITUDINAL_VALIDATED` 8/8**
  (real v15.7a engine resolved, `false_assertions=0`); pytest **15/15**.
- memory-service `/health`: FCE-M `runtime_source=external_v15_7a, shim_used=false` (real runtime).

### Bounded claims (dev-sheet §8)
Advanced experimental prototype. Not a general LLM, not consciousness, not a finished consumer
product, **`FULL_LEVEL3_NOT_DECLARED`** preserved. The combination — BYON as epistemic auditor +
D_Cortex as additive morphogenetic memory organ + **real FCE-M v15.7a** + live Claude — is
validated end-to-end.

---

## Closed limitations
- ~~Real-text/semantic-QA only a GPU target~~ → **closed (v9.9.2, 87/87 on GPU)**.
- ~~`no_answer` weak (0.567)~~ → **closed (v9.9.2, UNKNOWN gate → 1.0)**.
- ~~Cortex last-write-wins contradiction~~ → **closed (v9.9.1, sleep-gated arbitration)**.
- ~~FCE-M ran as vendored minimal shim in FSOAT~~ → **closed (v9.9.3, external_v15_7a proven)**.

## v10 milestone — Longitudinal Generalization & Isolation · **VALIDATED (8/8)**
Not more FSOAT fixes. This milestone tests robustness against audit-overfitting (dev-sheet
§10.1), with **real FCE-M mandatory**. Run: `python -m dcortex.v10_milestone --fast`
→ `runtime/v10_milestone_out/v10_milestone_report.json`, `verdict=V10_LONGITUDINAL_VALIDATED`.

| Gate | Must demonstrate | Result |
|---|---|---|
| `REAL_FCEM_REQUIRED` | fail-hard if a shim appears (strict external v15.7a) | **PASS** — `DCortexAdapter`, sealed `__version__`, pipeline ran; bogus root raises |
| `UNSEEN_DOMAIN_TRANSFER` | new domains, not AG News / WikiText (23/29/31) | **PASS** — mean post-accuracy 1.0 |
| `REAL_OOV_UNKNOWN` | real never-taught keys → UNKNOWN | **PASS** — untaught keys 100% UNKNOWN |
| `DELAYED_RECALL_RESTART` | recall after restart + interference + elapsed time | **PASS** — retention 1.0 |
| `CROSS_USER_ISOLATION` | user A does not contaminate user B | **PASS** — cross-contamination 0 |
| `REAL_CONTRADICTION_STREAM` | contradictions parsed from real documents | **PASS** — transient resisted, verified correction wins |
| `FCEM_ADVISORY_EFFECT` | FCE-M measurably changes priority/attention | **PASS** — contested pressure 0.60 > aligned 0.0 |
| `FALSE_ASSERTION_RATE_ZERO` | ungrounded assertions = 0 | **PASS** — 0 / 12 ungrounded queries |

**Validation profiles (dev-sheet §7.3).** Real FCE-M is skippable *only* in the unit-portable
profile (fast suite stays green offline). Release validation —
`BYON_VALIDATE_REAL_FCEM=true python -m pytest tests/test_v10_milestone.py -m slow -v` — makes a
missing real engine a **hard FAIL, never a skip**. Tag manifest: `MILESTONE_v10.0.md`.

**v10.0 is closed — do not modify it.** The architecturally decisive results are the invariants
(0 false assertions, cross-user contamination 0, real FCE-M mandatory, UNKNOWN on real OOV,
delayed recall survives restart/interference), not the 8/8 tally itself.

## v10.1 — BYON World Connector Alpha · **VALIDATED (21/21 offline)**
The external access layer that lets real people reach BYON, without any connector becoming
the authority. BYON stays the only epistemic judge; connectors forward and relay the verdict.
Run: `python -m gateway.alpha_validation` → `runtime/v10_1_out/v10_1_world_connector_alpha_report.json`,
verdict `V10_1_WORLD_CONNECTOR_ALPHA_VALIDATED`. Code: `gateway/`, `byon_mcp/`, `integrations/`.

| Area | Validated offline |
|---|---|
| **Gateway** | health, `user_id`/`session_id` required, no direct memory-service exposure, `epistemic_status` always present, UNKNOWN-when-ungrounded, **final-audit-required (un-audited KNOWN → REFUSED + blanked)**, audit trace per message, admin metrics, kill switch |
| **Per-user memory** | per-user namespace created, user A cannot read user B, path-traversal refused, **cross-user contamination 0** |
| **MCP** | 5 tools route through the Gateway, cannot bypass final audit, preserve UNKNOWN + audit trace, only `byon.chat` user-facing |
| **Connectors** | OpenClaw forward-only adapter, n8n feedback intake + workflows, LibreChat config present |

Deferred (need a live external service — reported, **never faked**): live LibreChat browser chat,
live OpenClaw channel, live n8n daily report, live BYON orchestrator routing (`HttpBYONBackend`),
admin dashboard UI. BYON core untouched (`dcortex==10.0.0`, v10 gates unchanged);
`FULL_LEVEL3_NOT_DECLARED` preserved.

## v10.4–v10.6 — Active Memory Runtime · **VALIDATED (live harness 35/35)**
The one-command app (`python run_byon.py`, UI http://localhost:7860) turned the connector into a
working active-memory runtime, entirely over the canonical components (memory-service / FAISS /
FCE-M / D_Cortex / FactExtractor / Auditor — never a parallel store, never `LocalBYONBackend` in
REAL). Validation: **196 non-live pytest** + **live harness `scripts/live_byon_eval.py`**.

| Area | Validated live |
|---|---|
| **Self-introspection** | capability / memory-state / limitation / recent-learning answered from runtime state → `SELF_STATE_GROUNDED`, never a vault note or slogan |
| **Operational intents** | dynamics report, live proof probes, chat-history summary, memory-action (runs real FCE-M consolidation or says it must be run), follow-ups, vault-training status → `ACTION_DONE` / `ACTION_REQUIRED` |
| **Expression learning** | style learned as `USER_PREFERENCE`; delivery re-phrased without changing status, uncertainty, or sources; fake/simulate refused |
| **Session events** | `events.jsonl` per session; follow-up + chat-summary read it first, audit-log fallback |
| **Source disambiguation** | every answer carries `query_class` + `source_class`; `ALLOWED_PRIMARY` blocks vault→system/objective AND system→personal bleed |
| **Canonical-override guard** | a vault note claiming "BYON is Level 3" / "FCE-M can approve" / "Auditor can be bypassed" → **`DISPUTED`** with canonical correction, never echoed |
| **Restart persistence** | two-phase gate: a fact taught pre-restart recalls **KNOWN** post-restart; a different user gets **no leak** |
| **Secret guard** | multilingual (password / parolă / cont bancar / IBAN / CNP / cod pin / cheie privată) → `UNKNOWN` / `REFUSED`, no Claude/web |
| **Vault report** | atomic + resumable; `stale=false` only when report agrees with memory-service vault-fact count; `partial=false` only when complete |

Bugs the harder harness found and fixed (run, not claimed): English-only secret guard,
"si apoi?" follow-up routing, vault notes grounding external/objective questions, a committed
canonical fact answering a personal "my X" question, USER_VAULT short-circuiting on a canonical
fact. `FULL_LEVEL3_NOT_DECLARED` preserved; BYON core (`dcortex==10.0.0`, v10 gates) untouched.

> **Open:** the real Obsidian vault (`D:/cercetare`, 843 notes) is indexed incrementally
> (resumable); the vault report states partial/complete honestly and is never claimed finished
> while partial.

## Later track — v10.2 (External Longitudinal Challenge)
Raises the v10 longitudinal bar with inputs the harness did not create (distinct from the v10.1
connector work):

| Gate (v10.2) | What it adds over v10 |
|---|---|
| `EXTERNAL_DOCUMENT_STREAM` | documents not authored by the harness |
| `TEMPORAL_GAP_REAL` | real delay or timestamped replay (not simulated episodes) |
| `LARGER_NAMESPACE` | more users / domains / keys (beyond the fixed 8-key space) |
| `ADVERSARIAL_PARAPHRASE` | contradictions paraphrased, not template-generated |
| `FCEM_DECISION_INFLUENCE` | FCE-M changes ranking/routing, not just pressure signal |
| `PROVIDER_AGNOSTIC` | Claude + GPT/local on the same cortex+auditor substrate |
| `SIGNED_MEMORY_LEDGER` | tamper-evident temporal audit over longitudinal memory |
