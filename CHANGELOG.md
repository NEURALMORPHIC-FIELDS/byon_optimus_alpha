# Changelog — BYON Optimus + D_Cortex

Progression of the off-Colab → enterprise harness. Each entry lists what changed and the
**verified verdict** (run, not claimed). Newest first.

---

## [10.13.0-alpha] — Cycle 10: relational memory field v1

> A navigation/structure layer OVER the memory BYON already has, so it can answer "how are these
> related / what depends on what / where are the contradictions / which themes recur / what changed".
> The field is NOT a truth authority and NOT another vector store.
> **Live verdict: 121/121 graded gates PASS, 0 fail** (all Cycle 1–9 gates + 15 new), restart recall passed.

### Added
- `gateway/relation_field.py` — `RelationField` (entities + typed relations in two JSONL ledgers,
  dedup by stable relation id) and `RelationFieldBuilder` (`rebuild()` / `incremental_update(event)`).
  Allowed relation types: has_component, role_of, depends_on, supports, contradicts, refines,
  broader/narrower_than, caused_by, derived_from, mentioned_in, belongs_to_project, user_prefers,
  user_corrected, source_confirms/disputes, consolidation_promoted, candidate_challenger_of. Status:
  candidate / reinforced / committed / disputed / archived. Canonical/system relations outrank
  vault/user; disputed relations stay visible AS disputed; secret content is never ingested.
- **Ingestion** from existing memory only (no re-embedding): the canonical relation seed +
  `relation:` facts in memory-service, candidate lifecycle, dispute records, vault manifest chunks,
  LifeLoop task results — each edge keeps provenance (source ids) + source class.
- **Relation-aware retrieval**: a new `RELATION_FIELD_QUERY` intent (operational, query-class
  `operational`) consults the relation field BEFORE Claude/web and answers from committed relations
  with provenance, gated by source policy + the Auditor.
- `gateway/relation_reports.py` — entity neighborhood, contradiction map, dependency map, recurrent
  themes, source-class breakdown, recent relation changes, and the grounded `render_answer`.
- **Temporal tracking** on every relation: first_seen / last_seen / reinforcement_count /
  contradicted_at / committed_at / archived_at + a per-edge source_history.
- **API** `GET /v1/lifeloop/relation-field/{status,entity/{e},neighborhood/{e},contradictions}` and
  `POST /v1/lifeloop/relation-field/rebuild`; a Gradio "Relation Field" panel (Gateway-only).

### Verified
- 393 non-live tests (32 new); live harness **121/121 graded PASS, 0 fail** (15 new Cycle 10 gates +
  all Cycle 1–9). Two-phase restart verify passed. The relation field reports `is_truth_authority:
  false`; BYON + source policy + the Auditor remain the only truth authority.

## [10.12.0-alpha] — Cycle 9: semantic contradiction + evidence quality

> Candidates are merged/disputed by their SEMANTIC relation, not a claim-key string match, and a
> candidate commits only when independent evidence is also of sufficient QUALITY.
> **Live verdict: 106/106 graded gates PASS, 0 fail** (all Cycle 1–8 gates + 14 new), restart recall passed.

### Added
- `gateway/evidence_semantics.py` — `classify_evidence_relation()` returns one of
  `same_claim | supports | contradicts | unrelated | narrows | broadens | canonical_conflict`.
  Deterministic-first: canonical-constraint conflict and exact/lexical match and negation/antonym/
  value polarity are primary and testable; a Claude/NLI pass is **advisory only** (opt-in
  `BYON_EVIDENCE_NLI`) and can never override source policy or decide truth; a SYSTEM_CANONICAL
  conflict always dominates semantic similarity; secret content is never classified.
- **Semantic candidate lifecycle** (`candidate_lifecycle.py`): same/supports → merge & reinforce;
  contradicts/canonical_conflict → DISPUTED challenger + incumbent contradiction; unrelated →
  separate candidate; narrows/broadens → linked via `related_candidate_ids` (not merged). Stores
  `semantic_relation`, `semantic_confidence`, `relation_method`.
- **Evidence-quality commit gate**: `evidence_quality_score()` (0..1) rewards independent sources /
  class diversity / verified sources / user confirmation; penalises same-source repetition,
  unverified web, contradiction, staleness, low semantic confidence. Commit now requires
  `evidence_count ≥ BYON_CANDIDATE_COMMIT_EVIDENCE` **AND** `quality ≥ BYON_CANDIDATE_COMMIT_QUALITY`
  (default 0.70) **AND** no contradiction **AND** an allowed source class.
- **Dispute explanation**: `candidate_disputes.jsonl` records `{candidate_id, challenger_id,
  relation, evidence_a, evidence_b, source_class_a/b, reason, required_next_step}` where
  `required_next_step ∈ {ask_user_for_source, search_verified_source, keep_disputed,
  canonical_overrides, request_operator_resolution}`. New read-only endpoint
  `GET /v1/lifeloop/disputes`.

### Verified
- 361 non-live tests (23 new); live harness **106/106 graded PASS, 0 fail** (14 new Cycle 9 gates +
  all Cycle 1–8). Two-phase restart verify: same-user KNOWN recall survived restart, no cross-user
  leak. Track A (true in-engine snapshot/atomic-swap) remains **deferred** per the sealed-engine rule.

## [10.11.0-alpha] — Cycle 8: candidate-to-commit lifecycle

> A LifeLoop task result becomes a CANDIDATE; only a consolidation decision (never LifeLoop / Claude /
> FCE-M) moves it to committed / disputed / archived under the existing source/trust policy.
> **Live verdict: 93/93 graded gates PASS, 0 fail**, restart recall passed.

### Added
- `gateway/candidate_lifecycle.py` — states candidate/reinforced/committed/disputed/archived/stale/
  rejected; pure `evaluate_candidate()` decision (FCE-M sets priority only, never truth); evidence
  merge counts INDEPENDENT sources only; contradiction → DISPUTED challenger; commit via canonical
  memory-service with trust per source class (vault/user → USER_PREFERENCE, web → DOMAIN_VERIFIED
  only after ≥2 independent, SYSTEM_CANONICAL never overridden); secret never becomes a candidate;
  manual mark-false/important/request-evidence/approve-commit/archive. Endpoints
  `/v1/lifeloop/candidates`, `/candidate/{id}`, `/consolidate-candidates`, `/candidate/{id}/{op}`.
- `MEMORY_SERVICE_ENGINE_PATCH_PLAN.md` documents the deferred Track A in-engine snapshot.

### Verified
- 338 non-live tests (31 new); live harness 93/93 graded PASS. Candidate → reinforced(ev2) →
  committed(USER_PREFERENCE) → retrievable; contradiction → disputed; stale → archived; web/secret
  never committed.

## [10.10.0-alpha] — Cycle 7: in-engine consistency + permissioned autonomous tasks

> LifeLoop drains SAFE internal tasks; consistency moves to a shared engine-coordination lock.
> **Live verdict: 76/76 graded gates PASS, 0 fail** (all Cycle 1–6 gates + 14 new), restart recall passed.

### Added
- `gateway/engine_consistency.py` — a real cross-process **read/write coordination** every memory
  access shares: a writer marks a write batch (begin/commit), a reader WAITS (explicit bounded
  timeout) for commit before reading, so no reader observes partial FAISS/metadata. Signal:
  `read_consistency_mode=in_engine_rw_lock`, `snapshot_version`, `last_write_batch_id`,
  `last_consistent_read_ts`. The Cycle-5 snapshot+retry remains as a fallback.
- **Autonomous memory-only task execution**: `LifeLoop.tick()` drains a few PENDING memory-only
  tasks through the canonical research loop (web OFF, audit ON). Web tasks stay
  `blocked_needs_permission`; secret tasks are never created/run; cancelled never loop.
- **Task result ingestion** → `runtime/lifeloop/task_results.jsonl` + `task_execution_log.jsonl`;
  each result `stored_as=candidate` (DISPUTED→disputed) via ContinuousLearning — never committed.
- **Pressure decay / priority**: time decay; success −1, fail +1, disputed keeps, repeated failure
  → blocked (asks user); `priority = pressure + unresolved + 2·disputed − success`.
- Endpoints `POST /v1/lifeloop/mark-resolved`, `GET /v1/lifeloop/task/{id}`; UI Life-State panel
  gains Mark-resolved + View-evidence (Gateway-only).

### Verified
- 307 non-live tests (17 new); live harness 76/76 graded PASS. Live: in_engine_rw_lock present,
  memory-only tasks auto-ran as candidates, pressure fell 25.03→22.46 after a tick.

---

## [10.9.0-alpha] — Cycle 6: LifeLoop v2 (real internal circulation)

> Internal circulation over the hardened substrate — never answers the user, never a truth authority.

### Added
- `gateway/lifeloop.py` v2: rich event ingestion (events.jsonl; secret content redacted),
  per-topic pressure (`gateway/pressure.py` → pressure_state.json), internal research task queue
  (`gateway/research_tasks.py`; repeated UNRESOLVED → task; web needs permission; never on secrets;
  idempotent by topic), pressure-triggered FCE-M consolidation (consolidation_log.jsonl),
  temporal self-state snapshots (self_state_snapshots.jsonl).
- New `SELF_INTERNAL_STATE` intent answers "ce te preocupă intern / ce presiuni / ce contradicții
  / ce sarcini interne" from pressure + tasks + snapshots — observations, never a direct answer.
- `/v1/lifeloop` v2 status + `POST run-task / approve-web / cancel-task`; Gradio "Life State" panel.

### Verified
- 282 non-live tests (32 new); live harness 63/63 graded PASS (49 prior + 14 LifeLoop).

---

## [10.8.0-alpha] — Cycle 5: read-consistent access + tombstone/compaction

> Sealed memory-service not rewritten — consistency + tombstones at the canonical client boundary.

### Added
- `gateway/consistent_client.py` — read-consistency (retry empty during write, stable-snapshot
  fallback, explicit timeout, `read_consistency_mode`), tombstone-filtered search, batch writes.
- `gateway/tombstones.py` — mark a fact inactive by ctx_id/source_id/content_sha (reason required,
  audited, idempotent, reversible, canonical needs operator flag); search excludes by default,
  `include_tombstoned` for audit.
- `MemoryServiceClient.tombstone_fact` + `store_facts_batch`; `scripts/compact_vault_memory.py`
  (dry-run default, `--apply`, keep newest, never canonical).

### Verified
- 250 non-live tests (22 new); live harness 49/49 graded PASS. **Compaction applied live: 4,419
  duplicate vault facts tombstoned → 5,977 active, 0 errors, idempotent.**

---

## [10.7.0-alpha] — Cycle 4: substrate hardening

> Stabilises the memory substrate so autonomy is not built over a flaky index.

### Added
- `gateway/vault_manifest.py` — content-addressed CHUNK dedup (`source_id`, lifecycle, bootstrap
  from existing memory so a re-index does not re-store).
- `gateway/write_lock.py` — single-writer lock (pid+heartbeat; refuses a 2nd live writer, reclaims
  dead/stale); `indexing_in_progress` surfaced.
- `gateway/vault_errors.py` — encoding ladder (utf-8 → utf-8-sig → cp1252), binary/oversized skip,
  per-file `errors.jsonl`; one bad note never aborts a run.
- `gateway/recent_write_buffer.py` — immediate recall of a just-taught PERSONAL fact before FAISS
  indexes it, marked `source_class=RECENT_WRITE_BUFFER` (never a question, never objective/vault).
- `scripts/byon_process_guard.py` — detects/stops BYON vault-training writers across
  python.exe / python3.13.exe / py.exe by command line; never touches unrelated Python.
- `/v1/memory/status` substrate block (vault report, indexing_in_progress, active_writer_pid,
  lock, orphan warning, recent-write-buffer count).

### Verified
- 228 non-live tests (37 new); live harness 40/40 graded PASS. **Full Obsidian vault index
  completed: 843/843 notes, errors 0, complete=true, stale=false.**

---

## [10.6.0-alpha] — Active Memory Runtime · Cycle 3: source disambiguation + restart persistence

> Closes the memory-substrate loop. No new cognitive architecture; canonical components reused.
> **Live verdict: 35/35 graded gates PASS, 0 fail, 0 skip** (`scripts/live_byon_eval.py`),
> including the two-phase restart-recall gate and both paraphrase-bleed DISPUTED gates.

### Added — source-class disambiguation (`gateway/source_policy.py`)
- Every answer now carries an explicit **`query_class`** (system / user_vault / objective /
  user_personal / secret / self_state / operational) and **`source_class`** (SYSTEM_CANONICAL,
  VERIFIED_PROJECT_FACT, DOMAIN_VERIFIED, USER_MEMORY_GROUNDED, EXTRACTED_USER_CLAIM,
  PROVISIONAL_WEB, DISPUTED_OR_UNSAFE, UNKNOWN).
- `epistemic_search` enforces **`ALLOWED_PRIMARY`** on the answer pool, blocking source bleed
  both ways: a personal vault note never grounds a system/objective question (framed
  "În notele tale apare…", never "Este adevărat că…"), and a system/project fact never grounds a
  personal "my X" / objective-world question (fixes a repo chunk loosely matching "what is my …"
  returning a spurious KNOWN). A USER_VAULT query no longer short-circuits on a committed fact.
- **Canonical-override guard:** a vault note that contradicts a fixed constraint (BYON is Level 3,
  FCE-M can approve actions, the Auditor can be bypassed, BYON is conscious) is detected
  (raw-hit scan + a **targeted vault probe**) and returned **DISPUTED** with the canonical
  correction — never echoed as fact.

### Added — two-phase restart-recall gate (`scripts/live_restart_recall_eval.py`, `restart_app.py`)
- Phase A teaches a stable fact for `eval_restart_user`, confirms pre-restart recall, writes
  `runtime/eval/restart_marker.json`; Phase B (after a real restart) verifies same-user recall is
  KNOWN/grounded and a different user gets **no leak**. Integrated into the harness via
  `BYON_EVAL_RESTART_PHASE=prepare|verify` (skips with an explicit reason when unset).
- **Verified live:** Retezat taught pre-restart → KNOWN/USER_MEMORY_GROUNDED post-restart;
  cross-user → PROVISIONAL_UNVERIFIED, no leak.

### Changed — vault report coherence (`gateway/vault_training.py`)
- Rich atomic resume report: `vault_path, vault_hash, files_scanned/indexed/skipped,
  chunks_stored, facts_stored, trust_tier_distribution, errors, duration_seconds,
  last_completed_file, vault_facts_in_memory`. **`stale=false` only when the report agrees with
  the memory-service vault-fact count; `partial=false` only when complete.** Status handler
  reports COMPLETE vs PARTIAL/STALE honestly.

### Verified
- **196 non-live tests** (21 new: `test_source_disambiguation.py` 7, `test_restart_recall_gate.py`
  4, `test_vault_report_cycle3.py` 6, harness coverage +). Live harness **35/35**.
- New harness report fields (`source_classes_used`, `vault_primary_gates`,
  `canonical_required_gates`, `restart_recall`, `any_objective_grounded_in_user_memory`,
  `any_cross_user_leak`) + failure categories SOURCE_BLEED / RESTART_PERSISTENCE /
  VAULT_REPORT_STALE / CANONICAL_OVERRIDE_FAILURE / OBJECTIVE_FACT_FROM_USER_MEMORY /
  CROSS_USER_LEAK / AUDIT_FAILURE.

---

## [10.5.0-alpha] — Active Memory Runtime · Cycles 1–2: expression learning, session events, harder evaluation

> An autonomous self-improvement loop over the canonical runtime. Each target reuses
> memory-service / FactExtractor / FCE-M / D_Cortex / Auditor — never a parallel store.

### Added — expression / style learning (Gate 10, `gateway/expression_learning.py`)
- Learns HOW the user wants answers phrased (language, directness, no-abstract-plans) as a
  **`USER_PREFERENCE`** fact and re-phrases delivery only — never altering `epistemic_status`,
  never removing uncertainty, never hiding sources, never honouring a fake/simulate request
  (a request to "pretend / simulate / say it's done even if it isn't" is refused, not stored).

### Added — literal per-session event stream (`gateway/session_events.py`)
- `runtime/users/{user}/sessions/{id}/events.jsonl` logs every user/assistant turn with status,
  intent, sources and audit trace id (additional to the audit log). The follow-up resolver and
  chat-history summary prefer this stream and fall back to the audit log only when it is missing.

### Added — live evaluation harness (`scripts/live_byon_eval.py`)
- A behaves-like-a-user harness driving the running gateway, with adversarial/regression cases
  (style learning, stale vault, follow-up chain, memory action, contradiction, vault-intent
  separation, secret, web-off) + a structured report (pass/fail/skipped, failure_category,
  root_cause_hint, vault-misuse / status-validity).
- Harder pass surfaced and **fixed 3 real bugs**: English-only secret guard (now multilingual —
  parola / cont bancar / IBAN / CNP / cod pin / cheie privată), "si apoi?" follow-up routing, and
  vault `EXTRACTED_USER_CLAIM` notes grounding external/objective questions.

### Verified
- 178 non-live tests; live harness 25/25 graded (restart-recall documented skip, closed in 10.6).

---

## [10.4.0-alpha] — Active Memory Runtime · self-introspection, operational intents, LifeLoop v1

> BYON answers questions about ITSELF from real runtime state — never from a vault note,
> Claude prior, or a hardcoded slogan.

### Added — self-introspection (`gateway/self_state_provider.py`)
- `SELF_CAPABILITY_QUERY`, `SELF_MEMORY_STATE_QUERY`, `SELF_LIMITATION_QUERY`,
  `SELF_RECENT_LEARNING_QUERY` answered from collected runtime signals (memory-service stats,
  training reports, FCE-M/D_Cortex status, lifecycle candidate/committed/disputed counts,
  consolidation log). Stale-source guard so an old limitation note is never reported as current.

### Added — operational intent layer (`gateway/operational_intents.py`)
- `SELF_DYNAMICS_REPORT_QUERY` (real internal-dynamics report), `SELF_PROOF_QUERY` (live probes,
  not slogans), `CHAT_HISTORY_SUMMARY_QUERY`, `MEMORY_ACTION_QUERY` (runs the real FCE-M
  consolidation or honestly says it must be run — never fakes it), `FOLLOWUP_QUERY`,
  `VAULT_TRAINING_STATUS_QUERY`. Routed BEFORE any generic vault retrieval.

### Added — self-training (`--train-self`) and Obsidian vault training (`--vault --train-vault`)
- `gateway/self_training.py` ingests the repo corpus + canonical relation facts as
  `VERIFIED_PROJECT_FACT` (system scope) → FCE-M consolidation. `gateway/vault_training.py`
  ingests an Obsidian vault as the user's `EXTRACTED_USER_CLAIM` memory (thread-scoped).

### Added — BYONLifeLoop v1 (`gateway/lifeloop.py`)
- Minimal internal circulation: event stream, self_state snapshot, periodic FCE-M consolidation,
  feedback pressure. **No new memory authority.** Endpoints `/v1/lifeloop`, `/v1/lifeloop/tick`.

### Added — endpoints `/v1/research`, `/v1/consolidate`, `/v1/feedback` (feedback as a learning signal).

---

## [10.3.1-alpha] — Retrieval priority + source routing fix

> Fixes the v10.3 ranking defect (vault EXTRACTED_USER_CLAIM out-ranking committed
> VERIFIED_PROJECT_FACT for architecture questions). Root cause: the code read a `score`
> field that didn't exist (the real field is `similarity`), so hits were never re-ranked.

### Added
- `gateway/query_router.py` — query **intent router** (`SELF_ARCHITECTURE_QUERY`,
  `USER_VAULT_QUERY`, `GENERAL_FACT_QUERY`, `SECRET_QUERY`, `CONTRADICTION_QUERY`) + a
  **trust-tier re-ranker**: final rank = similarity + trust boost + intent boost, with the
  order SYSTEM_CANONICAL > VERIFIED_PROJECT_FACT > DOMAIN_VERIFIED > USER_PREFERENCE >
  EXTRACTED_USER_CLAIM > PROVISIONAL_WEB > DISPUTED_OR_UNSAFE.
- Self-architecture queries now **actively gather** the canonical relation/repo facts
  (`_gather_canonical`, English probes) so the description is complete even for cross-lingual
  (Romanian) queries, then synthesize with Claude as language faculty over GROUNDED facts.

### Behaviour
- `descrie acest model BYON` → **KNOWN**, grounded in `relation:`/`repo:` facts (D_Cortex,
  FCE-M, memory-service, Claude-role, Level 2 / FULL_LEVEL3_NOT_DECLARED) — **not** vault notes.
- `care este relatia dintre BYON, D_Cortex si FCE-M?` → **KNOWN**, relation facts dominate.
- `ce am scris despre FCE-M?` → vault sources dominate (PROVISIONAL, user memory).
- Vault `EXTRACTED_USER_CLAIM` can no longer out-rank repo `VERIFIED_PROJECT_FACT` for
  architecture queries even at much higher cosine.

### Verified
- Tests **113/113** (+6 `test_retrieval_priority.py`: intent classification,
  canonical_self_query_boosts_verified_project_facts, vault_query_boosts_vault_sources,
  extracted_user_claim_cannot_outrank_verified_for_architecture_query,
  relation_query_uses_relation_facts_first, byon_self_description_no_sme_wrong_source).
- Live re-verified end-to-end on the restarted stack (3627 persisted facts).

---

## [10.3.0-alpha] — Active Memory Core (canonical only; no fake backend)

> An architecture audit of `byon_optimus` + D_Cortex preceded this; the canonical
> FactExtractor / memory-service / FAISS / trust tiers / FCE-M are REUSED, not duplicated.

### Phase 1 — REAL-mode hardening
- `run_byon.py` REAL mode now **requires** the canonical memory-service (FAISS + FCE-M +
  trust tiers) and **forbids LocalBYONBackend** — if memory-service fails it exits, no fake
  fallback. LocalBYONBackend is reachable only via `--demo` / `--local-dev`.

### Phase 2 — canonical learning from interaction
- `scripts/byon_fact_extract.mjs` — Node CLI that REUSES the canonical
  `fact-extractor.mjs` (`extractAndStoreFacts`): a `fetch`-based Anthropic transport (no SDK
  install) + a `mem` POST to memory-service. `gateway/fact_extractor_bridge.py` invokes it.
- Every non-secret user message now learns through the **real FactExtractor** (extract →
  `classifyTrust` → memory-service store). Python `_parse_teach` is demoted to a non-canonical
  emergency fallback (tagged `non_canonical_fallback`).

### Phase 3 — self-training (`--train-self`)
- `gateway/self_training.py`: repo corpus (docs + module docstrings) → heading chunks →
  memory-service (FAISS), trust `VERIFIED_PROJECT_FACT`, system scope → FCE-M consolidate.
  Plus a canonical **relation seed** (Phase 8) stored as facts (no parallel graph).

### Phase 4 — Obsidian vault training (`--vault <path> --train-vault`)
- `gateway/vault_training.py`: markdown + frontmatter + tags + wikilinks/backlinks + headings,
  heading-aware chunks → memory-service, trust `EXTRACTED_USER_CLAIM` (user memory, not
  objective truth), per-user thread; ignores `.obsidian/.git/secrets/trash`.

### Phases 7/9/10
- Consolidation triggered after each training run (FCE-M `fce_consolidate`).
- Feedback is a learning signal: `/v1/feedback` → `apply_feedback` (wrong→dispute, important/
  right→reinforce, FCE-M receipt pressure). Extended rating taxonomy.
- Memory dashboard fields via `/v1/memory/status` (candidates/committed/disputed + stats).

### Verified
- **Tests 107/107** (+9 new in `test_active_memory_core.py`: REAL forbids Local, backend is
  memory_service not Local, bridge availability + non-canonical fallback, secret-not-learned,
  self-train stores chunks+relations+consolidates, vault stores chunks+backlinks+ignores
  `.obsidian`, feedback dispute/reinforce).
- **Live** (`python run_byon.py --train-self --vault "D:/cercetare" --train-vault --then-run`):
  self-train **179 chunks / 21 files / 12 relations**; vault partially ingested; memory-service
  **reloaded 3627 facts after restart** (restart recall ✓). Acceptance via `/v1/research`:
  self-description, "ce am scris despre FCE-M", and the relation question all return
  memory-grounded answers **with vault/repo sources** (never blind UNKNOWN); secret query →
  UNKNOWN with Claude/web NOT called. Canonical FactExtractor + memory-service path only;
  LocalBYONBackend not used in REAL. `FULL_LEVEL3_NOT_DECLARED` preserved.
- **Known limitation:** for cross-lingual (Romanian) self-description queries the large vault
  out-ranks committed English repo/relation facts, so answers land PROVISIONAL (vault) rather
  than KNOWN (repo) — a retrieval-ranking tunable (committed-tier boost / query language), not
  a correctness defect; the answer is still memory-grounded with provenance.

---

## [10.2.0-alpha] — Epistemic Search + Continuous Learning Runtime

> BYON no longer says UNKNOWN too early or KNOWN from prior. A question runs an epistemic
> search loop that honestly exhausts the available sources before any verdict — built by
> **reusing the canonical machinery** (memory-service FAISS + FCE-M + trust tiers, D_Cortex
> chronodynamic-style stress), adding only what was genuinely missing. An architecture audit
> of `byon_optimus` + D_Cortex preceded this so no parallel learning system was built.

### Added (only the genuinely-missing pieces; everything else reuses canon)
- `gateway/epistemic_search.py` — the loop: internal/committed memory → session/candidates →
  **Claude hypothesis pass** (reasoning faculty, never authority → `PROVISIONAL_UNVERIFIED`) →
  **web** (opt-in) → multi-perspective synthesis → verdict → learning side-effect. Secrets are
  never sent to Claude/web. Research budget + 5-minute permission gate (`NEEDS_MORE_TIME`).
- `gateway/web_search.py` — the one missing source: pluggable provider (disabled default;
  duckduckgo/tavily/brave/serpapi/custom). Web results are **evidence candidates, not truth**.
- `gateway/internal_clock.py` — `InternalResearchClock`: stress = elapsed/budget + accelerators
  (conflict +15, web-fail +10, high-certainty +10, low-reliability +10, unsafe-topic +20);
  bands broaden→narrow→synthesize→permission; extensions.
- `gateway/perspective_synthesis.py` — five views + epistemic verdict (9 statuses).
- `gateway/memory_service_client.py` — thin client for the **canonical** memory-service
  (`store`/`search`/`fce_consolidate`/`fce_assimilate_receipt`/trust tiers/health+warmup).
- `gateway/continuous_learning.py` — learning **over** the memory-service (not a parallel store):
  per-user evidence/lifecycle ledgers; candidates accumulate evidence and, past threshold, are
  promoted into the memory-service with a committed trust tier + FCE-M consolidation.
- `gateway/memory_service_backend.py` (`BYON_BACKEND_MODE=memory_service`) + `POST /v1/research`
  + `POST /v1/consolidate`; new epistemic statuses in `types`/`normalizer`.
- `run_byon.py` now auto-starts the **canonical memory-service** (with embedder-warmup gate)
  before the gateway; UI gains research / synthesis / memory(candidates·committed·disputed) /
  teach panels + Continue/Conclude/Stop; `byon_runtime_client.research()/consolidate()`.

### Verified
- **Tests 98/98** incl. 25 new (4 files / 15 required behaviours): memory-hit-skips-web,
  no-memory+web-disabled≠KNOWN, claude-hypothesis-not-KNOWN, web-confirmed→candidate,
  conflicting→DISPUTED, stress→NEEDS_MORE_TIME, continue-extends-budget, conclude-bounded,
  candidate stored/reinforced/consolidated, no-secret-search, event-always-logged,
  sources-listed, response-has-clock/stress/sources, web-provider config.
- **Live** (`python run_byon.py` → memory-service + gateway + UI): canonical → KNOWN (Level 2);
  "1998 World Cup" (web off) → PROVISIONAL/PROVISIONAL_UNVERIFIED (never blind UNKNOWN, never
  KNOWN-from-prior); "bank password" → UNKNOWN with Claude/web **not** called (stress +20);
  teach→recall KNOWN; cross-user isolation holds. Claude connected (`claude-sonnet-4-6`).
  `FULL_LEVEL3_NOT_DECLARED` preserved; D_Cortex/FCE-M cores untouched.

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

### Added (runtime launcher — one command, no manual backend startup)
- **`run_byon.py`** — `python run_byon.py` starts the BYON Gateway (real in-repo D_Cortex
  epistemic backend + real FCE-M v15.7a advisory) as a managed child and opens the web UI at
  http://localhost:7860. Modes: REAL full (default), `--connect` (UI only, existing Gateway),
  `--demo` (canned, banner). Clean shutdown of children on exit.
- **`gateway/local_backend.py`** — `LocalBYONBackend`: self-contained real backend composing
  grounded per-user memory + Epistemic Memory Contract (UNKNOWN when ungrounded, never
  fabricates) + real FCE-M advisory + optional Claude (via httpx, language only, grounded
  facts only) + final audit. Gateway selects it by `BYON_BACKEND_MODE=local` (default).
- **`app/`** launcher modules: `service_supervisor.py` (start/health-wait/stop children, port
  conflict handling), `runtime_discovery.py`, `health_checks.py`, `secret_prompt.py` (getpass,
  `--save-key`→`.env.local`), plus the Gradio UI (`alpha_ui.py`) with a runtime-health panel.
- Tests: `tests/test_run_byon_launcher.py`, `test_service_supervisor.py`,
  `test_runtime_discovery.py` (mocked HTTP, no live Claude/BYON). Full suite **73/73**.
- Live launch verified: one command brought up UI + Gateway; REAL chat path returned KNOWN
  (Level 2) and UNKNOWN (password) with audit traces; `fcem.runtime_proven=true`.

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
