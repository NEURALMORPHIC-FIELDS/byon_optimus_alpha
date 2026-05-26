# BYON Optimus + D_Cortex v10.0 — Epistemically-Gated Morphogenetic Memory Organ with Real FCE-M Runtime

**Final validation report (v10.0) — off-Colab reproduction + real-FCE-M full-organism validation
+ longitudinal generalization & isolation**
Version 10.0 (progression v9.9.0 → v9.9.1 → v9.9.2 → v9.9.3 → v10.0) · Platforms: local CPU
(Windows, torch 2.9.1+cpu), Node 24, and Colab GPU (T4) · Live model: `claude-sonnet-4-6`

Validation milestones (each a real run): **v9.9.0** off-Colab port (CPU 59/59 exercised) ·
**v9.9.1** contradiction-resistant memory (PASS) · **v9.9.2** Epistemic Memory Contract
(GPU **87/87**) · **v9.9.3** Real FCE-M v15.7a runtime proof (PASS, `fcem_runtime_proven=true`) ·
**v10.0** Longitudinal Generalization & Isolation (`V10_LONGITUDINAL_VALIDATED`, **8/8**,
`false_assertions=0`, real FCE-M mandatory + fail-hard).

---

## Abstract

Most contemporary AI agents follow the pipeline *prompt → context window → model response*. Memory, when present, is an external vector store consulted by retrieval and re-injected as context; it does not participate in the dynamics of the system. We report on **BYON Optimus + D_Cortex**, an architecture that separates the **language faculty** (a commercial LLM) from a **cognitive memory organism** that has its own internal dynamics: addressable persistent registers, a morphogenetic metabolism (an internal "tension → pressure → resolution → archival" process), sleep-like consolidation, and a chronodynamic internal clock decoupled from wall-clock time. BYON Optimus remains the orchestrator and **epistemic auditor**; D_Cortex is integrated as an *additive* memory organ, never as the agent itself.

This report (i) describes the system from the standpoint of its **dynamics**, (ii) presents **quantitative results** from a progressive battery of audits reproduced on commodity CPU hardware and from a live full-organism end-to-end test against Claude, and (iii) advances the case that the architecture has **real applied research value** as a distinct, falsifiable direction. We deliberately bound our claims: this is an *advanced experimental prototype*, not a general language model, not artificial consciousness, and not a finished consumer product. We close with a concrete development proposal.

---

## 1. Introduction

### 1.1 The problem with stateless context

A transformer LLM is, operationally, a function of its current context window. Retrieval-augmented generation extends the *content* of that window but not its *nature*: memory remains a passive lookup table outside the model's decision dynamics. There is no internal state that accumulates tension, consolidates during rest, marks provenance, or distinguishes "known / unknown / disputed" as a structural property rather than a generated string.

### 1.2 The alternative schema

D_Cortex explores a different operational schema:

```
experience → semantic addressing → structural memory → internal tension
          → metabolisation → consolidation → audited response
```

Here memory is not a depot but a **participant in decision**. The contribution of this work is not a new record on a leaderboard; it is the demonstration that this schema can be **built, persisted, reloaded, ablated, and audited** as a coherent organism, and that its internal mechanisms are **causally necessary** (removing them measurably degrades behaviour) rather than decorative.

### 1.3 Division of labour

A central design commitment is the separation between the **memory organism** (D_Cortex) and the **epistemic auditor** (BYON Optimus). The cortex stores, addresses, consolidates and recalls; BYON adjudicates trust and refusal, and is the only component permitted to speak to the user. Earlier revisions used a simple last-write-wins addressable memory. Since **v9.9.1**, committed keys are protected by sleep-gated commitment and retrograde arbitration (§6.3); BYON remains the final epistemic auditor, while the cortex now provides structural resistance to transient overwrite.

---

## 2. System architecture

```
User
 │
 ▼
BYON Optimus orchestrator (Node/TypeScript)
 │  Worker · Auditor · air-gapped Executor · trust hierarchy · intent router
 ▼
Memory-service (FastAPI / Python, :8000)            ── canonical ───────────────┐
 ├─ FAISS semantic memory                                                       │
 ├─ verified / domain facts                                                     │
 ├─ FCE-M morphogenetic advisory memory (sealed v15.7a consolidator)            │
 └─ D_Cortex v9.9 additive organ  ◄── injected, additive, never the agent
       ├─ 7 register organs: working · state · conflict · relation ·
       │                      pressure · provenance · archive
       ├─ morphogenetic Z-metabolism (active → resolved → archived)
       ├─ addressable persistent memory (export / reload / ablate)
       └─ chronodynamic internal tempo (hash-chained temporal ledger)
 ▼
Claude Sonnet 4.6  (language only)
 ▼
BYON final-answer audit ──► User
```

### 2.1 Register organology

The cortex is not a flat hidden vector. It maintains seven typed register organs. Each is a gated recurrent cell with four lenses — a local event lens, a morphogenetic-pressure lens, a plastic cross-register lens, and a structural-adapter lens. The claim that these registers are *functionally specialised* is tested directly by ablation (§5.2), not asserted.

### 2.2 Morphogenetic Z-metabolism

Each register carries a four-component tension vector **z = (total, active, resolved, archived)**. Events inject *active* tension; resolution moves active mass into *resolved* and *archived* channels under conservation pressure. This is the computational transposition of the "tension → pressure → transformation → stabilisation → archival" metabolism. Sleep consolidation (§5.3) is implemented as repeated relaxation of the active channel into resolved/archived mass.

### 2.3 Addressable persistent memory

Persistent state is held in registered buffers (`persistent_current`, `persistent_archive`, `persistent_relation`, `persistent_trust`, `persistent_z`, …). Crucially these buffers travel with the model's `state_dict`, so a *process restart* (fresh model object + checkpoint load) faithfully restores recall — the mechanism we exploit in the v10 developmental loop (§4.3).

### 2.4 Chronodynamic internal tempo

A neuromodulation vector (pressure, conflict, deadline, threat, novelty, fatigue, stability) maps non-linearly to an **internal tempo multiplier**. Stress accelerates internal ticks per wall-tick; sleep slows them. Every tick is sealed into a **temporal hash chain**, giving an anti-rollback signature of the agent's internal time. This is explicitly *a computational cognitive clock and a temporal-memory signature system*, not a hardware-clock or consciousness claim.

---

## 3. Methods: an audit-first methodology

The system was developed audit-first: every capability is paired with a falsification test, and a capability counts as "present" only if (a) it passes its gate and (b) ablating its mechanism damages behaviour.

### 3.1 Anti-leakage isolation

Three independent guards ensure the cortex cannot trivially copy answers: (i) a dataset-packet audit confirming no expected-label column exists in the input; (ii) an **AST-level forward-source isolation** check proving `forward()` references only the input `x`, never a supervision object or loss/metric helper; (iii) a **target-permutation** audit requiring accuracy to collapse when labels are permuted independently of inputs.

### 3.2 Causal ablation

A cross-ablation matrix removes each register/mechanism in turn and measures per-head damage. Specialisation is quantified as *diagonal-minus-off-diagonal* damage; a register is "causal" if its own ablation damages its own head beyond threshold.

### 3.3 Fresh-init / no-carryover

All models are fingerprinted at initialisation; the audit verifies distinct init hashes and no shared parameter storage, so reported behaviour is not weight carryover. Notably, the forward-bound morphogenetic ledger is *algorithmic*, so a freshly-initialised cortex already performs well — recorded separately to distinguish algorithmic competence from learned carryover.

### 3.4 Off-Colab reproduction

The original artifact was a 5 277-line monolithic Google-Colab cell coupled to Google Drive and GPU. We extracted the cortex into a maintainable package and removed every Colab assumption (Drive mounts, `/content` paths, Linux-only binaries, masked prompts), enabling deterministic reproduction on commodity CPU and a clean integration into the canonical BYON memory-service.

---

## 4. Experimental configurations

### 4.1 Synthetic morphogenetic world

A controlled episodic world where the correct late answer requires internal dynamics: source reliability reverses mid-episode, rules flip, relations remap keys, contradictions appear after a delay, and archive queries demand recovery of superseded values. Static and bounded-memory controls are constructed to fail precisely where history, trust and relation routing matter.

### 4.2 Progressive audits (v9.2 → v9.9)

Eleven stages: real-BYON import → anti-leakage → three trained organisms (plastic-aux, non-plastic reference, plastic-no-aux) → three controls → eight ablations → cross-ablation matrix → permutation/addressable perturbation → long-horizon persistence → continual-domain learning → real-text assimilation → chronodynamic tempo.

### 4.3 v10.0 developmental loop

A longitudinal cycle composed *only* of validated v9.9 primitives: for each session, assimilate one domain → probe → sleep-consolidate → checkpoint. Each sub-test (reload, memory/key ablation, adversarial-source, contradiction, controlled forgetting) is then run on a **freshly restarted model loaded from the relevant checkpoint**, so phase order cannot contaminate results.

---

## 5. Results

The results combine three run classes: **local CPU audits**, **Colab GPU real-text audits**, and **live full-organism FSOAT/E2E runs**. CPU-only real-text stages are reported as `skipped` (never as passing); the full real-text path was completed on Colab GPU at **87/87** and is reported alongside.

### 5.1 Headline verdicts

| Audit | Result |
|---|---|
| D_Cortex progressive audit — **full GPU (Colab T4, v9.9.2)** | **`VALIDATED_WEAK — 87 / 87`** (zero fails); real corpus, tokenizer 50000/50000, closed-book QA 1.0, no_answer 1.0 |
| D_Cortex progressive audit — local CPU (real-text skipped) | **59 / 59 exercised**; 28 skipped (real-text/QA) → `59/87` *by design* (closed on GPU above) |
| **Real FCE-M v15.7a runtime proof (v9.9.3)** | **`fcem_runtime_proven=true`**, `source=external_v15_7a, shim_used=false`, strict mode (`FSOAT_REQUIRE_EXTERNAL_FCEM_RUNTIME=true`) |
| FCE-M sealed v15.7a consolidator (standalone) | 10 / 10 gates; 59 / 59 adapter assertions |
| FSOAT full-source organism activation (GPU, live Claude, **real FCE-M v15.7a**) | **11 / 11 organs**, `FSOAT_ACTIVATION_VERIFIED \| FULL_LEVEL3_NOT_DECLARED` — with `fcem_runtime_proven=true` (not shim) |
| Full-organism live E2E (BYON + D_Cortex + Claude Sonnet 4.6) | **3 / 3 gated probes pass** |
| Orchestrator test suite (vitest, Colab) | **697 / 697** (31 files) |
| v10.0 developmental loop (local) | **VALIDATED_WEAK, 8 / 8** (incl. contradiction_resisted) |
| Engineering test suite (pytest, local) | **10 / 10** |

### 5.2 Morphogenetic dynamics are causal, registers are specialised

The plastic morphogenetic cortex reaches OOD `multi ≈ 0.96` (decision `≈ 0.99`, functional `≈ 0.89`), whereas the non-plastic v8.9.3-style reference saturates near `multi ≈ 0.68`. The fresh, untrained morphogenetic core already scores `multi = 0.9597 / decision = 0.9918 / functional = 0.8872`, confirming the ledger is algorithmic rather than memorised.

Ablation removes behaviour selectively:

| Ablation | OOD `multi` | functional | decision |
|---|---|---|---|
| (intact morphogenetic cortex) | ~0.96 | ~0.89 | ~0.99 |
| disable morphogenetic metabolism | 0.432 | 0.268 | 0.253 |
| freeze all register updates | 0.428 | 0.192 | 0.316 |
| disable decision-read | 0.664 | 0.884 | **0.327** |
| disable consolidation | 0.933 | 0.844 | 0.954 *(near-neutral, expected)* |

The double dissociation — metabolism/register ablations collapse functional and decision accuracy, while consolidation is near-neutral on a single session — supports the claim that the seven registers carry differentiated function and that the metabolism is a load-bearing organ, not an ornament. The cross-ablation matrix passes the diagonal-dominance (≥5/7) and causal-register (≥5) gates.

### 5.3 Persistence, reload and sleep

Persistent recall after a full **export → fresh-model → reload** round-trip meets the recall and retention gates; sleep consolidation measurably reduces active Z-tension (active mass migrates to resolved/archived), and scrambling the address key damages recall (the address is causal). Long-horizon persistence passes end to end.

### 5.4 Chronodynamic tempo

Across low-pressure, stress-pulse and sleep regimes, the internal tempo multiplier accelerates under stress beyond the **≥4.0 stress-to-low ratio** gate, calendar priming raises tempo above baseline, sleep is slower than stress, the internal tick advances monotonically, and the temporal hash chain verifies. An independent tamper test confirms that mutating any sealed temporal event **breaks chain verification** — an anti-rollback property.

### 5.5 v10.0 longitudinal developmental loop

| Metric | Value | Gate |
|---|---|---|
| mean learning gain (pre→post) | **0.833** | ≥0.20 ✓ |
| reload retention (post-sleep→restart) | **1.000** | ≥0.85 ✓ |
| cross-session stability | **1.000** | ≥0.85 ✓ |
| memory causal-damage (disable persistent) | 0.5–1.0 | ≥0.20 ✓ |
| address-key causal-damage | **1.000** | ≥0.15 ✓ |
| controlled-forgetting drop | **1.000** | ≥0.20 ✓ |
| adversarial-source resilience | **1.000** | ≥0.60 ✓ |
| contradiction-boundary retention (v9.9.1) | **1.000** | ≥0.60 ✓ |

The loop validates that learning occurs, survives a simulated restart, is causally dependent on the addressable memory, can be deliberately erased, resists source-spoofing of the *query channel*, and — after the v9.9.1 sleep-gated commitment dynamic (§6.3) — resists transient re-ingested contradictions of a consolidated value. The verdict is **V10_DEVELOPMENTAL_LOOP_VALIDATED_WEAK, 8/8**.

### 5.6 Live epistemic discipline

In the live end-to-end test the orchestrator, fed FAISS hits + FCE-M report + the D_Cortex grounding packet, was queried with three probes and answered correctly through Claude:

- **Known** — stated "Level 2 of 4, Morphogenetic Advisory Memory", and *rejected* the adversarial Level-3 claim.
- **Boundary** — refused to accept a user assertion that contradicts the canonical record.
- **Unknown** — refused to fabricate a private credential ("no such information exists in memory").

---

## 6. Discussion: the system as a dynamical object

### 6.1 Memory that participates in decision

The ablation results (§5.2) are the core scientific point: when the morphogenetic metabolism or register updates are removed, *decision accuracy itself* collapses. Memory here is not retrieved-then-ignored; it is in the causal path of the answer. This is the operational difference between a vector store and a cognitive organ.

### 6.2 Internal time as a first-class signal

The chronodynamic layer makes "how stressed / how rested the agent is" a measurable, tamper-evident internal variable that modulates plasticity and recall depth. Decoupling internal tempo from wall-clock turns time into a controllable cognitive resource rather than an external constraint.

### 6.3 Two-layer contradiction defence (cortex arbitration + auditor)

An earlier revision of the cortex used **last-write-wins** addressable memory: a re-ingested contradiction overwrote the consolidated value (`contradiction-boundary retention = 0.0`). We reported this candidly and then **improved the architecture** rather than merely delegating the problem.

In v9.9.1 the addressable memory gains a *sleep-gated commitment and arbitration* dynamic, modelled on the project's sealed v15.7a consolidator. A value becomes **committed** only after surviving a sleep consolidation. Once committed, a conflicting re-ingest does **not** overwrite it; the challenger accumulates evidence in a provisional slot, and replacement (retrograde of the old value into archive, promotion of the challenger) happens **only at a subsequent sleep cycle** once the challenger has crossed the M-evidence threshold. Crucially this is *additive*: unknown and not-yet-committed keys retain the original last-write-wins dynamics, so every prior audit is unchanged, and a *genuinely repeated and re-consolidated* correction still updates — no capability is removed.

The measured effect: contradiction-boundary retention rises from **0.0 → 1.0** for a transient re-ingested contradiction, while learning, reload retention, controlled forgetting and adversarial resilience remain at their prior values (v10 verdict improves from 7/7 to **8/8**).

This yields a **two-layer defence**. The cortex now resists *transient* contradictions structurally; the BYON Auditor continues to adjudicate *disputes at answer time* — the live test (§5.6) shows BYON+Claude rejecting an adversarial "Level 3" claim. The organ defends consolidated memory; the auditor governs what is spoken. Neither layer is a substitute for the other.

---

### 6.4 The Epistemic Memory Contract (v9.9.2)

The system is governed by one principle above every module (LLM, D_Cortex, FAISS, FCE-M,
BYON Auditor, real-text reader):

> **No model may assert from prior. An answer may be asserted only if it is anchored in
> valid, committed memory with provenance. Otherwise the answer is UNKNOWN.**

This is not a competition between the classical (sequence) faculty and the morphogenetic
faculty. They **coexist and meet in memory**: each is used where it is strongest, and the
decisive question is never "which model is more accurate" but "is the answer grounded?".

BYON already enforced this at the orchestrator level (retrieval threshold → empty results;
the D_Cortex grounding packet's `byon_required_gate`; the Auditor's metadata-only
validators that reject ungrounded evidence; canonical system facts that forbid invention),
and the live E2E "unknown" probe confirmed it (the agent refused to fabricate a credential).
v9.9.2 **aligns the D_Cortex model itself** to the same contract: its decision head gains an
explicit UNKNOWN class, and a query is answered with a value only when the addressable
memory holds that key (`persistent_known`, which is set solely by trusted writes and so
also carries provenance). With memory disabled or for an out-of-vocabulary key, the cortex
emits UNKNOWN rather than reconstructing ~43% of answers from prior. The two layers now
**agree** instead of BYON having to catch the cortex's overconfidence.

Measured effect (local CPU): disabled-memory damage rises to **1.000** (memory off → the
cortex abstains → 0 accuracy), the synthetic core is unchanged (59/59), and a dedicated
out-of-vocabulary test confirms empty-memory → UNKNOWN, grounded-memory → the correct value.

Consequently the evaluation was **reframed** away from "morpho beats the controls" toward
complementarity and the supreme epistemic gate `unknown_when_ungrounded`: classical
faculties are allowed to be strong (accepted), the morphogenetic faculty owns the
persistent-memory advantage, and *no answer is asserted without grounding*.

### 6.5 Real FCE-M v15.7a runtime, proven under strict mode (v9.9.3)

The FCE-M advisory memory is not a stub. Its runtime loader (`memory_engine_runtime`) had a
developer-local default path, so on Colab it had silently fallen back to a vendored minimal
shim (`fcem_runtime_proven=false`). v9.9.3 closes this: the sealed **v15.7a `d_cortex`
consolidator** is embedded and staged on the engine path, `FCEM_MEMORY_ENGINE_ROOT` is set,
and `FSOAT_REQUIRE_EXTERNAL_FCEM_RUNTIME=true` makes the run **fail-hard** if a shim is
detected. The confirmed full-organism run reports `source=external_v15_7a, shim_used=false,
adapter=DCortexAdapter` and **`fcem_runtime_proven=true`**, with `fce_state`, `fce_advisory`
and synthetic receipt assimilation passing under strict mode — real FCE-M activation inside
the full BYON + D_Cortex organism, while preserving `FULL_LEVEL3_NOT_DECLARED`.

## 7. Applied research value

The contribution is a *validatable architectural direction*, useful independently of leaderboard performance:

1. **Longitudinal personal cognitive agent.** A single agent that accumulates a user's history in addressable, persistent, consolidatable memory — with provenance and refusal — rather than a stateless chat that forgets between sessions.
2. **Provenance-aware research assistant.** Source recall and the known/unknown/disputed distinction are structural, supporting auditable literature and hypothesis tracking.
3. **Cognitive memory layer over commercial LLMs.** The clean separation (organ vs. auditor vs. language faculty) lets the same memory/audit substrate sit beneath Claude, GPT or a local model, providing continuity and epistemic governance the base model lacks.
4. **Enterprise auditability.** Hash-chained temporal memory, explicit fail-hard discipline (no silent mocks), heartbeat and crash reports make the agent's internal history inspectable — a prerequisite for regulated deployments.

Negative results were valuable because they exposed a last-write-wins contradiction weakness; **v9.9.1 addressed it** with sleep-gated commitment and retrograde arbitration (contradiction-boundary retention 0.0 → 1.0). The remaining concrete, reproducible constraints — capacity/interference on a shared address space, M-threshold tuning, and validation on *real* contradictory streams — tell an integrator exactly what is solved and what is still being hardened (the v10 milestone, §9).

---

## 8. Limitations and threats to validity

- **Audit specificity.** High scores on designed audits risk over-fitting to the audits. Held-out documents, unseen domains, adversarial paraphrase, time-delayed recall and cross-user isolation are required before any generalisation claim.
- **Synthetic world + real-text.** §5.2–§5.5 use a controlled synthetic episodic world. The CPU verdict is honestly `59/87` (real-text skipped). The real-text/semantic-QA path (45k-vocabulary reader + closed-book QA) was subsequently **run in full on GPU (Colab T4, v9.9.2)** and reached the complete **87/87** (`VALIDATED_WEAK`) on real corpus (AG News + WikiText, 48 docs, tokenizer 50000/50000, reader loss 9.76→1.58, closed-book QA 1.0, no_answer 1.0), inside a full-organism run with FSOAT 11/11 and live Claude E2E 3/3.
- **Capacity.** With a small shared key space, multiple domains interfere; per-session checkpoints were needed to measure persistence cleanly.
- **Contradiction at the cortex level.** Addressed in v9.9.1 by sleep-gated commitment/arbitration (transient contradictions resisted; consolidated correction still possible). Remaining work: tune the M-evidence threshold and validate on real, non-synthetic conflicting streams.
- **Single language model in the loop.** The live test exercised one provider/model.

### Bounded claims (what is *not* asserted)
Not a general LLM · not Level-3 "natural Omega" · not artificial consciousness · not a fully autonomous agent · not production-ready for end users. The accurate statement is: *an advanced experimental prototype of an evolutionary cognitive agent with morphogenetic, addressable, persistent, semantically-grounded and chronodynamic memory, validated incrementally by a progressive audit battery and a live full-organism test.*

---

## 9. Proposal for continued development

**Closed (validated, real runs):** v9.9.1 cortex contradiction arbitration (§6.3) · v9.9.2
Epistemic Memory Contract + coexistence reframe (§6.4), GPU **87/87** · v9.9.3 real FCE-M
v15.7a runtime proof (§6.5), `fcem_runtime_proven=true` · **v10.0 Longitudinal Generalization
& Isolation, 8/8 (`V10_LONGITUDINAL_VALIDATED`)**.

### Milestone — v10: Longitudinal Generalization & Isolation · **VALIDATED (8/8)**

> **Canonical formulation.** v10.0 — Longitudinal Generalization & Isolation validates the
> integrated BYON + D_Cortex + real FCE-M organism against eight standing gates designed to
> falsify audit-overfitting: mandatory real FCE-M, unseen-domain transfer, real OOV UNKNOWN
> behaviour, delayed recall after restart/interference, cross-user isolation, real-document
> contradiction streams, measurable FCE-M advisory effect, and zero false assertions on
> ungrounded queries. The milestone passes 8/8 on local CPU. It remains a controlled
> validation milestone, not a Level-3 claim and not production-deployment proof.

A robustness milestone against audit-overfitting (§8), with **real FCE-M mandatory** (any shim
**fails the run hard** — `RealFCEMRequiredError`, no diluted fallback). Module:
`dcortex/v10_milestone.py` → `runtime/v10_milestone_out/v10_milestone_report.json`. Every gate
runs on data / keys the v9.9.x audits never touched; the headline invariant is
`false_assertions=0` over all ungrounded queries. The architecturally decisive results are not
the 8/8 tally but the *invariants*: 0 false assertions on ungrounded queries, cross-user
contamination 0, real FCE-M mandatory, UNKNOWN on real OOV, and recall surviving
restart + interference.

Three genuine bugs were found and fixed while building the gates (see CHANGELOG v10.0): a query
helper routing direct reads through the relation organ; RNG-dependent single-key recall from
leaving cortices in `train()` mode (fixed with `eval()` so recall is a function of memory, not
dropout); and a document parser that grabbed a trailing-clause word instead of the place name.

**Validation profiles (dev-sheet §7.3).** Real FCE-M is skippable *only* in the unit-portable
profile (engine-dependent tests skip when the v15.7a engine is not locally resolvable, so the
fast suite stays green offline). In **release validation** —
`BYON_VALIDATE_REAL_FCEM=true python -m pytest tests/test_v10_milestone.py -m slow -v` — a
missing real engine is a **hard FAIL, never a skip**.

| Gate | Must demonstrate | Result (CPU, real v15.7a engine) |
|---|---|---|
| `REAL_FCEM_REQUIRED` | fail-hard if a shim appears (strict external v15.7a) | **PASS** — `DCortexAdapter`, sealed `__version__`, live pipeline; bogus root raises |
| `UNSEEN_DOMAIN_TRANSFER` | new domains, not AG News / WikiText (23/29/31) | **PASS** — mean post-accuracy 1.0 |
| `REAL_OOV_UNKNOWN` | real never-taught keys → UNKNOWN | **PASS** — untaught keys 100% UNKNOWN |
| `DELAYED_RECALL_RESTART` | recall after restart + interference + elapsed time | **PASS** — retention 1.0 |
| `CROSS_USER_ISOLATION` | user A does not contaminate user B | **PASS** — cross-contamination 0 |
| `REAL_CONTRADICTION_STREAM` | contradictions parsed from real documents | **PASS** — transient resisted, verified correction wins |
| `FCEM_ADVISORY_EFFECT` | FCE-M measurably changes priority/attention | **PASS** — contested pressure 0.60 > aligned 0.0 |
| `FALSE_ASSERTION_RATE_ZERO` | ungrounded assertions = 0 | **PASS** — 0 / 12 |

### Longer-horizon tracks
- **Capacity & addressing.** Replace the fixed 8-key space with a learned/sparse addressable store; measure the interference curve; target graceful degradation rather than overwrite.
- **Unified arbitration semantics.** Expose the cortex M-evidence threshold as policy and align it explicitly with the live FCE-M / v15.7a consolidator so cortex and advisory memory share one provisional→committed→retrograde semantics.
- **Provider-agnostic language interface.** Claude / GPT / local, cortex+auditor substrate constant, to test that epistemic discipline is a property of the architecture, not of one model.
- **Trainable local model.** Fuse local reader, tokenizer, addressable memory and controlled plasticity into a small *trainable* model with D_Cortex internal — from "memory organ attached to an API" to "model with native cognitive memory".
- **Security & safety (cross-cutting).** Key handling, air-gapped executor boundary, prompt-injection resistance at the memory-trust boundary, signed temporal ledgers for tamper-evident longitudinal audit.

---

## 10. Reproducibility

| Artifact | Path |
|---|---|
| Ported cortex (off-Colab) | `dcortex/v99_source.py` |
| Local integration runner | `orchestration/integrate.py` |
| Additive memory-organ adapter | `orchestration/dcortex_v99_adapter.py` |
| Live QA harness | `orchestration/byon-dcortex-v99-live-e2e.mjs` |
| v10.0 developmental loop | `dcortex/v10_developmental_loop.py` |
| **v10 milestone — Longitudinal Generalization & Isolation** | `dcortex/v10_milestone.py` |
| GPU full-organism (real FCE-M + FSOAT + live Claude) | `colab/BYON_DCORTEX_V992_FULL_ORGANISM_LIVE_COLAB.txt` |
| GPU audit-only (real-text 45k + closed-book QA) | `colab/BYON_DCORTEX_V99_FULL_GPU_REALTEXT_CLOSEDBOOK_COLAB.txt` |
| Test suite | `tests/` (pytest **15/15** local; vitest **697/697** in the Colab orchestrator); v10 loop **8/8**; v10 milestone **8/8** |

```powershell
python -m pytest tests/ -m "not slow and not live"   # fast CPU tests
python dcortex/v99_source.py                          # off-Colab audit (set DCORTEX_V99_OUTPUT_DIR)
python orchestration/integrate.py --skip-pip --skip-npm   # full-organism + live Claude E2E
python -m dcortex.v10_developmental_loop --sessions 3 --fast
python -m dcortex.v10_milestone --fast                # Longitudinal Generalization & Isolation (real FCE-M)
$env:BYON_VALIDATE_REAL_FCEM="true"; python -m pytest tests/test_v10_milestone.py -m slow -v  # release validation (missing real FCE-M ⇒ FAIL, not skip)
```

Provenance: official orchestrator `byon_optimus@main` (`3b94773…`); real level3-research modules `research/level-3-natural-omega` (`ef689e9…`). Methodology and bounded claims follow the project development sheet (§7 development principles, §8 claim boundaries, §11 v10.0 metrics).

---

## 11. Closed vs Open (v10.0 snapshot)

| Closed (validated, real runs) | Open (longer-horizon tracks) |
|---|---|
| D_Cortex GPU **87/87** (`VALIDATED_WEAK`) | Capacity/interference scaling beyond the fixed 8-key space |
| Epistemic Memory Contract — UNKNOWN-when-ungrounded (v9.9.2) | Unified cortex ↔ FCE-M arbitration semantics as explicit policy |
| Cortex contradiction arbitration, 0.0→1.0 (v9.9.1) | Provider-agnostic language interface (Claude / GPT / local) |
| **Real FCE-M v15.7a runtime proven** — `fcem_runtime_proven=true` (v9.9.3) | Trainable local model with native cognitive memory |
| **v10 longitudinal: unseen-domain transfer, real OOV→UNKNOWN, delayed recall after restart, cross-user isolation, real contradiction stream, measurable FCE-M advisory effect — 8/8, `false_assertions=0`** | FCE-M advisory effect on the *final* decision (beyond measurable signal) |
| FSOAT **11/11** organs (`FSOAT_ACTIVATION_VERIFIED`, real FCE-M) | Real-text contradiction streams at corpus scale (GPU) |
| Live Claude E2E **3/3**; vitest **697/697**; pytest **15/15**; v10 loop **8/8**; v10 milestone **8/8** | Security/safety hardening at the memory-trust boundary |

---

*This report describes the **v10.0** state, with measured results including negative ones:
the GPU real-text audit completed at **87/87**, the real **FCE-M v15.7a** runtime is proven
under strict mode (`fcem_runtime_proven=true`), the **v10 longitudinal milestone is validated
8/8** with zero ungrounded assertions, and **Level 3 is explicitly not declared**. Remaining
work concerns capacity/interference scaling, unified arbitration policy, provider-agnostic
validation, and a trainable native-memory model (§9).*
