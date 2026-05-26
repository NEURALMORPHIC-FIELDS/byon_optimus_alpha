# colab — GPU notebooks

Two single-cell Colab sources. Pick by what you want to validate.

## 1. `BYON_DCORTEX_V992_FULL_ORGANISM_LIVE_COLAB.txt`  ← comprehensive, "tot tacâmul"

The **full organism, live, no economy**. One cell that:
- clones the official `byon_optimus`,
- boots the canonical memory-service (FAISS + FCE-M sealed v15.7a + injected D_Cortex organ),
- patches `server.py` with the `dcortex_v99_*` actions,
- runs the **full D_Cortex audit on GPU** (real-text 45k reader + closed-book QA + chronodynamic, full mode — no fast, no skip, no low-VRAM),
- runs **FSOAT** (full-source organism activation),
- runs the **live Claude QA gating harness** (known / contradiction-boundary / unknown).

Embeds the current **v9.9.2** science: UNKNOWN-when-ungrounded epistemic gate, contradiction
arbitration, convergence early-stop, schema-robust grounding adapter, fixed live-E2E scorer.

### Proposed model + runtime
- **GPU**: Runtime → Change runtime type → **T4** (free, sufficient) or **A100** (Colab Pro, fastest reader). 16 GB-class run; do NOT enable the 2 GB low-VRAM profile.
- **LLM (live audit)**: **`claude-sonnet-4-6`** (default, validated). For a stronger auditor, in a cell *above* run `import os; os.environ["LLM_MODEL"]="claude-opus-4-7"`.
- **API key**: add a Colab **Secret** named `ANTHROPIC_API_KEY` (recommended) or paste at the masked prompt. Never hard-code it.

### Run
1. Set GPU runtime.
2. (Optional) add the `ANTHROPIC_API_KEY` Colab Secret.
3. Paste the entire `.txt` into one cell and run.
Outputs (report + per-audit JSON/MD + verdict) are written under Drive / `/content`.

## 2. `BYON_DCORTEX_V99_FULL_GPU_REALTEXT_CLOSEDBOOK_COLAB.txt`  ← audit-only

Just the D_Cortex audit (no BYON service, no Claude). Use when you only want the cortex
verdict (real-text 45k + closed-book QA + chronodynamic) without standing up the orchestrator.
No API key needed.

---

Both are byte-faithful to `../dcortex/v99_source.py` in their D_Cortex body; the full-organism
file additionally embeds the fixed adapter and live-E2E harness and the Colab orchestration.
