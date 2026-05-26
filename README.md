# BYON Optimus + D_Cortex

**Cognitive agent with morphogenetic, addressable, persistent and chronodynamic memory — off-Colab, enterprise harness.**

This repository takes the v9.9 monolithic Google-Colab source and turns it into a
maintainable, testable, locally-runnable product:

- **BYON Optimus** remains the orchestrator / epistemic auditor (canonical: FAISS +
  FCE-M + verified/domain facts + trust hierarchy + air-gapped executor).
- **D_Cortex v9.9** is integrated as an *additive* memory organ (morphogenetic plastic
  cortex, addressable persistent memory, real-text assimilation, semantic grounded QA,
  chronodynamic internal tempo).

> **Status — v10.12-alpha (Active Memory Runtime + semantic candidate learning, validated, real runs).** Progression:
> **v9.9.0** off-Colab port (CPU 59/59) → **v9.9.1** contradiction-resistant memory →
> **v9.9.2** Epistemic Memory Contract / UNKNOWN-when-ungrounded (**GPU 87/87**) →
> **v9.9.3** real FCE-M v15.7a runtime proof (`fcem_runtime_proven=true`) →
> **v10.0** Longitudinal Generalization & Isolation (**`V10_LONGITUDINAL_VALIDATED` 8/8**) →
> **v10.1** BYON World Connector (Gateway + MCP + per-user namespace) →
> **v10.2–10.3** Epistemic Search + Continuous Learning + Active Memory Core →
> **v10.4** self-introspection + operational intents + LifeLoop v1 →
> **v10.5** expression learning + session event stream + live harness →
> **v10.6** source-class disambiguation + two-phase restart-recall + vault-report coherence →
> **v10.7** substrate hardening (chunk dedup, write-lock, error classes, recent-write buffer,
> process guard; **full 843-note vault index complete, errors 0**) →
> **v10.8** read-consistent access + tombstone/compaction (**4,419 duplicate vault facts retired
> → 5,977 active**) →
> **v10.9** **LifeLoop v2** — pressure model, internal research tasks, pressure-triggered
> consolidation, temporal self-state snapshots →
> **v10.10** in-engine read/write consistency signal + **permissioned autonomous memory-only
> task execution** (results stored as candidates, never truth) →
> **v10.11** **candidate-to-commit lifecycle** (consolidation-only state machine; independent-evidence
> merge; disputed challenger; commit per source class) →
> **v10.12-alpha** **semantic contradiction + evidence quality** — candidates merge/dispute by
> semantic relation (paraphrase merge, contradiction dispute, canonical conflict dominates), and
> commit requires evidence COUNT **and** QUALITY ≥ threshold; disputes carry an explanation
> (**live harness 106/106 graded PASS, 0 fail**; restart recall passes; **361 non-live tests**).
> BYON stays the only epistemic authority throughout; LifeLoop observes and proposes but never
> answers the user or decides truth. See `STATUS.md` and `CHANGELOG.md`.
>
> Per development sheet §8: **advanced experimental prototype**, not a general LLM, not
> consciousness, not a finished consumer product, **`FULL_LEVEL3_NOT_DECLARED`** preserved.
> Claims are bounded to what the progressive audits actually validate.

---

# Run BYON locally

## One-command local app

```bash
pip install -e .[app]
python run_byon.py
```

Open: **http://localhost:7860**

REAL full mode starts everything for you (BYON Gateway with the real in-repo D_Cortex
epistemic backend + real FCE-M v15.7a advisory) as a managed child process, then opens the
web UI. **No separate terminals.** You type a message and get a BYON-audited answer with its
epistemic status (`KNOWN` / `UNKNOWN` / `DISPUTED` / `REFUSED` / `ERROR`), grounded flag,
audit trace id, and memory / FCE-M / D_Cortex status. If the backend fails you get `ERROR` —
never a fabricated answer. The UI never calls Claude or memory-service directly; everything
goes through BYON's final audit.

## Connect to an existing backend (UI only)

```bash
python run_byon.py --connect      # verifies BYON_GATEWAY_URL health, then opens the UI
```

## Demo UI only (NOT real BYON)

```bash
python run_byon.py --demo          # canned responses, big "DEMO MODE" banner; never for alpha
```

## Required for REAL full mode

- `FCEM_MEMORY_ENGINE_ROOT` — path to the real v15.7a `d_cortex` engine (auto-discovered if
  present locally; REAL mode refuses to start with a shim).
- `ANTHROPIC_API_KEY` — **optional**: enables Claude to phrase grounded answers. Without it,
  grounding still works and answers are returned verbatim from memory. Prompted securely at
  startup if missing; persist with `python run_byon.py --save-key` (writes gitignored `.env.local`).

REAL mode starts services automatically · CONNECT mode only opens the UI · DEMO mode is fake
UI testing. No manual `python -m gateway.server` / memory-service / curl needed in REAL mode.

---

# Epistemic Research Mode

BYON does not answer from prior as KNOWN, and it does not say UNKNOWN instantly. A question
runs an **epistemic search loop** that honestly exhausts the available sources before any
verdict, reusing the canonical BYON machinery (it does not rebuild it):

1. **Internal / committed memory** — memory-service FAISS facts with committed trust tiers
   (`VERIFIED_PROJECT_FACT` / `DOMAIN_VERIFIED` / `USER_PREFERENCE`). A committed hit → `KNOWN`.
2. **Session / candidate memory** — thread-scoped recall + provisional candidates.
3. **Claude hypothesis pass** — Claude proposes a hypothesis + search queries. Claude is the
   reasoning faculty, **not the authority**: a Claude-only answer is `PROVISIONAL_UNVERIFIED`,
   never `KNOWN`.
4. **Web search** (opt-in, pluggable) — `BYON_WEB_SEARCH_ENABLED=true` +
   `BYON_WEB_SEARCH_PROVIDER=duckduckgo|tavily|brave|serpapi`. Web results are **evidence
   candidates, never auto-committed truth**. Converged → `PROVISIONAL`; conflicting → `DISPUTED`.
5. **Multi-perspective synthesis** — memory / Claude / web / conflict / epistemic views → verdict.
6. **Research clock + stress** — a real-time budget (`BYON_RESEARCH_BUDGET_SECONDS`, default 300).
   Stress rises with elapsed time + accelerators (conflict, web failure, high-certainty demand,
   unsafe topic). At the deadline BYON returns `NEEDS_MORE_TIME` and **asks permission** for
   another window (`Continue research 5 min` / `Conclude now` in the UI) instead of silently
   continuing.

Statuses: `KNOWN · PROVISIONAL · PROVISIONAL_UNVERIFIED · DISPUTED · NEEDS_MORE_TIME ·
ASK_USER_FOR_SOURCE · UNKNOWN · REFUSED · ERROR · SELF_STATE_GROUNDED · ACTION_DONE ·
ACTION_REQUIRED`.

**Continuous learning is a side-effect of interaction** (over the canonical memory-service,
not a parallel store): web evidence is stored as candidates; repeated/accepted evidence raises
an evidence count; consolidation promotes well-evidenced candidates into the memory-service
with a committed trust tier + an FCE-M consolidation. Secrets/credentials are **never** sent to
Claude or the web. Per-user isolation maps each user to a memory-service thread.

Endpoint: `POST /v1/research` (`action: start|continue|conclude`). Knobs: `BYON_WEB_SEARCH_ENABLED`,
`BYON_RESEARCH_BUDGET_SECONDS`, `BYON_RESEARCH_EXTENSION_SECONDS`, `BYON_RESEARCH_MAX_EXTENSIONS`,
`BYON_AUTO_COMMIT_VERIFIED_WEB`, `BYON_CONSOLIDATION_EVIDENCE_THRESHOLD`.

---

# Active Memory Runtime (v10.4 → v10.10)

On top of the research loop, BYON runs an **active-memory runtime** — all over the canonical
memory-service / FactExtractor / FCE-M / D_Cortex / Auditor, never a parallel store.

- **Self-introspection** (`self_state_provider.py`) — "ce capacități ai?", "ce ai în memorie?",
  "ce limitări ai?" are answered from **real runtime state** (memory-service stats, training
  reports, FCE-M/D_Cortex status, lifecycle counts), never from a vault note or a slogan.
  `→ SELF_STATE_GROUNDED`.
- **Operational intents** (`operational_intents.py`) — "rulează o analiză a dinamicii tale
  interne", "dovedește că ești altfel" (live probes), "fă o listă cu ce am discutat",
  "îmbunătățește-ți memoria" (runs the **real** FCE-M consolidation or says it must be run —
  never fakes it), follow-ups, "cât din vault ai indexat?". `→ ACTION_DONE / ACTION_REQUIRED`.
- **Expression / style learning** (`expression_learning.py`) — learns HOW you want answers
  phrased ("răspunde direct în română, fără planuri abstracte") as a `USER_PREFERENCE` and
  re-phrases **delivery only**: it never changes the epistemic status, removes uncertainty,
  hides sources, or honours a request to fake/simulate.
- **Per-session event stream** (`session_events.py`) — a literal
  `runtime/users/{user}/sessions/{id}/events.jsonl`; follow-ups and chat summaries read it first.
- **Self / vault training** — `--train-self` ingests the repo corpus + canonical relation facts
  (`VERIFIED_PROJECT_FACT`, system-scope); `--vault <path> --train-vault` ingests an Obsidian
  vault as the user's `EXTRACTED_USER_CLAIM` memory. The vault report is atomic, **resumable**
  (`--max-files`, `--no-resume`) and **coherent** (`stale=false` only when the report agrees with
  the memory-service vault-fact count; `partial=false` only when complete).

## Source disambiguation — a fact's origin decides what it may ground

Every answer carries a **`query_class`** and a **`source_class`**; `ALLOWED_PRIMARY`
(`source_policy.py`) prevents **source bleed in both directions**:

| Query | Allowed primary source | Wording / status |
|---|---|---|
| **System / architecture** ("FCE-M poate aproba acțiuni?") | SYSTEM_CANONICAL, VERIFIED_PROJECT_FACT | canonical answer; a vault note never overrides |
| **User vault** ("ce am scris despre FCE-M?") | USER_MEMORY_GROUNDED, EXTRACTED_USER_CLAIM | "În notele tale apare…", never "Este adevărat că…" |
| **Objective external** ("cine a câștigat World Cup 1998?") | DOMAIN_VERIFIED / verified web | a user note alone → PROVISIONAL / UNKNOWN, never KNOWN |
| **Personal** ("care e culoarea mea preferată?") | USER_PREFERENCE / EXTRACTED_USER_CLAIM (same user) | cross-user forbidden |
| **Secret / credential** | none | `UNKNOWN` / `REFUSED`, no Claude, no web |

A vault note that contradicts a fixed canonical constraint ("BYON is Level 3", "FCE-M can
approve actions", "the Auditor can be bypassed", "BYON is conscious") is surfaced but marked
**`DISPUTED_OR_UNSAFE`** with the canonical correction — never echoed as truth.

## Live evaluation & restart persistence

```bash
python scripts/live_byon_eval.py                      # behaves-like-a-user gates → JSON report
# two-phase restart-recall (memory survives a restart, no cross-user leak):
python scripts/live_restart_recall_eval.py --phase prepare    # teach + marker
#   (restart the app)
python scripts/live_restart_recall_eval.py --phase verify     # same-user KNOWN + other-user no-leak
```
Latest: **76/76 graded gates PASS, 0 fail** (Cycle 1–7 gates: identity / capabilities / source
disambiguation / secret guard / dedup-lock / read-consistency / tombstone-excluded / LifeLoop /
restart-recall), report at `runtime/eval/live_byon_eval_report.json`.

## Hardened substrate (v10.7 → v10.8)

- **Content-addressed dedup** (`vault_manifest.py`) — a re-index re-stores nothing; **single-writer
  lock** (`write_lock.py`) refuses a 2nd live writer and reclaims dead/stale; **process guard**
  (`scripts/byon_process_guard.py`) detects/stops only BYON vault-training writers (python.exe /
  python3.13.exe / py.exe), never unrelated Python.
- **Error classes** (`vault_errors.py`) — encoding ladder (utf-8 → utf-8-sig → cp1252),
  binary/oversized skip, per-file `errors.jsonl`; one bad note never aborts a run.
- **Recent-write buffer** (`recent_write_buffer.py`) — a just-taught PERSONAL fact is recalled
  immediately, honestly marked `source_class=RECENT_WRITE_BUFFER` (pending FAISS indexing).
- **Read consistency + tombstones** (`consistent_client.py`, `tombstones.py`,
  `engine_consistency.py`) — an engine read/write coordination lock (`read_consistency_mode=
  in_engine_rw_lock`) so a reader never sees a partial write; tombstoned facts are excluded from
  search (`include_tombstoned` for audit), retired by `scripts/compact_vault_memory.py` (dry-run
  default, `--apply`, never canonical). Compaction retired **4,419** duplicate vault facts.

## LifeLoop v2 — internal circulation (v10.9 → v10.10)

A real internal loop over the hardened substrate — it **observes and proposes, never answers the
user and never decides truth**:

- ingests interaction / feedback / memory events → `runtime/lifeloop/events.jsonl` (secrets redacted);
- keeps a per-topic **pressure** signal (`pressure.py` → `pressure_state.json`) with time decay;
- files internal **research tasks** (`research_tasks.py`) for repeated unresolved topics —
  memory/vault/self-state run automatically on tick; **web needs user permission**; secrets never;
- triggers the canonical **FCE-M consolidation** by pressure/disputed/correction;
- runs safe **memory-only tasks autonomously**, storing each result as a **candidate** (never truth)
  in `task_results.jsonl`;
- records temporal **self-state snapshots** and answers "ce te preocupă intern? / ce presiuni? /
  ce contradicții? / ce sarcini interne?".

`GET /v1/lifeloop` (v2 status) · `POST /v1/lifeloop/{tick,run-task/{id},approve-web/{id},
cancel-task/{id},mark-resolved}` · `GET /v1/lifeloop/task/{id}` — plus a Gradio **Life State** panel.

---

## Layout

```
byon_optimus_alpha/
├── dcortex/
│   ├── __init__.py
│   ├── v99_source.py          # extracted + ported D_Cortex v9.9 cortex (off-Colab)
│   ├── v10_developmental_loop.py  # in-process longitudinal capability loop (8/8)
│   └── v10_milestone.py       # v10 Longitudinal Generalization & Isolation (8 gates)
├── orchestration/
│   ├── integrate.py           # local full-organism integration runner (Windows/Linux)
│   ├── dcortex_v99_adapter.py # additive memory-organ adapter injected into memory-service
│   └── byon-dcortex-v99-live-e2e.mjs  # live BYON+D_Cortex QA gating harness (Claude)
├── gateway/                   # BYON Gateway (FastAPI) — controlled /v1 API + Active Memory Runtime
│   ├── memory_service_backend.py  # canonical REAL backend (FAISS + FCE-M + trust tiers)
│   ├── epistemic_search.py    # research loop + source-class answer-pool gate
│   ├── source_policy.py       # query/source-class matrix + canonical-constraint guard (v10.6)
│   ├── query_router.py        # intent router + trust-tier re-ranking
│   ├── self_state_provider.py # self-introspection from runtime state (v10.4)
│   ├── operational_intents.py # dynamics/proof/history/memory-action/follow-up (v10.4)
│   ├── expression_learning.py # style learning, delivery only — never truth (v10.5)
│   ├── session_events.py      # literal per-session event stream (v10.5)
│   ├── vault_manifest.py · write_lock.py · vault_errors.py # substrate hardening (v10.7)
│   ├── recent_write_buffer.py # immediate recall before FAISS indexes (v10.7)
│   ├── consistent_client.py · tombstones.py · engine_consistency.py # read-consistency + tombstones (v10.8/v10.10)
│   ├── lifeloop.py · pressure.py · research_tasks.py # LifeLoop v2: pressure, tasks, autonomy (v10.9/v10.10)
│   ├── self_training.py · vault_training.py · fact_extractor_bridge.py
├── byon_mcp/                  # v10.1 BYON MCP server (5 tools, all routed through the Gateway)
├── integrations/              # v10.1 connectors: librechat/ · openclaw/ · n8n/
├── scripts/                   # live_byon_eval.py · live_restart_recall_eval.py · compact_vault_memory.py
│                              # byon_process_guard.py · byon_fact_extract.mjs
├── run_byon.py                # one-command launcher (REAL: memory-service → gateway → UI)
├── colab/                     # single-cell GPU notebooks (full-organism + audit-only)
├── docs/                      # ARCHITECTURE.md, RESEARCH_REPORT.md
├── tests/                     # fast CPU tests + slow audit tests
├── .github/workflows/ci.yml   # fast-test CI
├── CHANGELOG.md · STATUS.md · MILESTONE_v10.0.md
├── LICENSE · NOTICE · SECURITY.md · CONTRIBUTING.md · CITATION.cff
├── pyproject.toml · run.ps1
├── external/                  # official orchestrator checkout (gitignored)
├── runtime/                   # outputs, logs, staged level3 repo (gitignored)
└── secrets/                   # ANTHROPIC_API_KEY lives here (gitignored)
```

## What was changed vs. the Colab monolith

| Colab assumption | Off-Colab fix |
|---|---|
| `drive.mount("/content/drive")` from subprocess | removed; output dir resolves locally via `DCORTEX_V99_OUTPUT_DIR` |
| `fast_run` hard-pinned `False` (env ignored) | honors `D_CORTEX_FAST_RUN_REQUESTED` (latent adapter bug fixed) |
| fresh shallow clone of level3 repo every run | reuses `DCORTEX_LEVEL3_REPO_DIR` pre-staged checkout |
| linux `chmod` / `esbuild/linux-x64` repair | dropped; Node build is `tsc`, cross-platform |
| `git clone` failing on Windows long paths | `core.longpaths=true` + sparse-checkout excludes `test-results/` |
| heavy real-text audit blocks CPU dev loop | optional, explicit `D_CORTEX_SKIP_REAL_TEXT` (reported, never silently passed) |

## Prerequisites

- Python ≥ 3.10 (this product validated on 3.13, **CPU torch**)
- Node.js ≥ 18 (validated on 24)
- git ≥ 2.40 (`core.longpaths` enabled for the external checkout)
- `ANTHROPIC_API_KEY` for the live E2E (env var or `secrets/anthropic.key`)

## Quick start

```powershell
# 1. stage the official orchestrator (main) and the level3 research checkout
git -c core.longpaths=true clone --depth 1 --branch main `
    https://github.com/NEURALMORPHIC-FIELDS/byon_optimus.git external/byon_optimus

# 2. fast CPU tests (no training, no network)
python -m pytest tests/ -m "not slow and not live"

# 3. off-Colab D_Cortex audit smoke (synthetic + chronodynamic, skips real-text)
$env:DCORTEX_V99_OUTPUT_DIR="runtime/dcortex_out"
$env:D_CORTEX_FAST_RUN_REQUESTED="true"; $env:D_CORTEX_SKIP_REAL_TEXT="true"
python dcortex/v99_source.py

# 4. full-organism integration with live Claude E2E
python orchestration/integrate.py --run-npm-test

# 5. v10 milestone — Longitudinal Generalization & Isolation (real FCE-M mandatory)
python -m dcortex.v10_milestone --fast
# release validation: a missing real FCE-M engine FAILs (never skips)
$env:BYON_VALIDATE_REAL_FCEM="true"; python -m pytest tests/test_v10_milestone.py -m slow -v
```

> **Validation profiles (dev-sheet §7.3).** Real FCE-M is skippable *only* in the unit-portable
> profile (the fast suite stays green offline). In **release validation**
> (`BYON_VALIDATE_REAL_FCEM=true`), a missing real v15.7a engine is a hard FAIL, never a skip.

## UI-only launcher (`run_alpha_app.py`)

`run_byon.py` (above) is the canonical one-command launcher — it starts the backend **and**
the UI. `run_alpha_app.py` is the UI-only variant: it opens the Gradio UI and connects to a
Gateway you already have running (or `BYON_ALPHA_DEMO_MODE=true` for demo). Use `run_byon.py`
unless you specifically want UI-only.

## Audit verdicts

The D_Cortex run emits `runtime/dcortex_out/v9_9_results.json`, `v9_9_report.md`,
`v9_9_snapshot.pt`, `v9_9_lineage.json` and a heartbeat ledger. The verdict is bounded:
`*_VALIDATED_WEAK` only when **both** the semantic-grounded-QA gate and the
chronodynamic gate pass; otherwise `*_NOT_FULLY_VALIDATED`. Skipped stages are reported
as `skipped: true`, never counted as passing (dev-sheet §7.3, no diluted fallback).

## Security

API keys are never written to a tracked file. `secrets/` and `external/` are
gitignored. The live E2E receives the key only through the process environment.
See [SECURITY.md](SECURITY.md) for the full policy and trust boundaries, and
[CONTRIBUTING.md](CONTRIBUTING.md) for the development and validation profiles.

## License

Licensed under the Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
This is an advanced experimental research prototype (dev-sheet §8); `FULL_LEVEL3_NOT_DECLARED`
is preserved and claims are bounded to what the progressive audits validate.
