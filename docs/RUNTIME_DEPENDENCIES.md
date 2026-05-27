# Runtime dependencies and the external FCE-M contract

This document states honestly what is bundled in this repository and what is resolved at runtime
from an external, sealed source. Nothing here pretends the FCE-M engine is bundled, because it is not.

## Bundled in this repository

- The **Gateway** (`gateway/`), the **UI/launcher** (`app/`, `run_byon.py`), the **MCP tools**
  (`byon_mcp/`), the **scripts** (`scripts/`), and the off-Colab **D_Cortex** port (`dcortex/`).
- The full test suite (`tests/`) and the live evaluation harness (`scripts/live_byon_eval.py`).
- The relational-memory layer, candidate lifecycle, LifeLoop, source policy and tombstone logic.

## External / not bundled

- **BYON Optimus orchestrator checkout** - consumed at runtime from
  `github.com/NEURALMORPHIC-FIELDS/byon_optimus` under `external/` (gitignored, not vendored).
- **FCE-M v15.7a consolidator** - a sealed external runtime. It is NOT in this repository. It is
  resolved at runtime via the environment variable below.
- **memory-service** - the canonical FastAPI + FAISS + trust-tier store; started as a child process
  by `run_byon.py` in REAL mode. It embeds the real D_Cortex engine and FCE-M.

## `FCEM_MEMORY_ENGINE_ROOT`

- Points at the sealed v15.7a `d_cortex` engine root, e.g.
  `.../fragmergent-memory-engine/13_v15_7a_consolidation`.
- The sealed package `__version__` begins with `0.1.0-extracted-from-v15.7a-sealed`.
- Auto-discovered locally if present; otherwise set it explicitly before starting REAL mode.

## Required version

- FCE-M **v15.7a** (the sealed consolidator). A shim or a different version is rejected in release
  validation. The runtime advertises `runtime_source=external_v15_7a, shim_used=false` when the real
  engine is loaded.

## How REAL mode fails if the engine is missing (fail-hard, no diluted fallback)

- Per development sheet section 7.3, REAL mode and release validation **fail hard** when the real
  FCE-M engine is absent. There is no silent shim and no diluted fallback.
- `run_byon.py` in REAL mode refuses to start with `LocalBYONBackend` (forbidden in REAL); the
  memory-service child must come up with the real engine or startup fails.
- The release milestone gate `REAL_FCEM_REQUIRED` (`dcortex/v10_milestone.py`) raises on a bogus or
  missing engine root rather than skipping.

## How to verify `runtime_proven`

- Check the memory-service health: it reports FCE-M `runtime_source=external_v15_7a, shim_used=false`.
- The milestone report (`runtime/v10_milestone_out/v10_milestone_report.json`) carries
  `fcem_runtime_proven=true` only when the real engine ran.
- Run: `BYON_VALIDATE_REAL_FCEM=true python -m pytest tests/test_v10_milestone.py -m slow -v`
  (a missing real engine is a hard FAIL here, never a skip).

## Which tests require the external engine

- The **slow** milestone tests (`tests/test_v10_milestone.py -m slow`) require the real FCE-M engine
  and a GPU/CPU run; they are the release-validation gates.
- The **unit-portable** suite (`python -m pytest -m "not slow and not live"`) runs offline and does
  NOT require the external engine; it exercises the Gateway, relation layer, lifecycle and policies
  with in-process fakes.
- The **live** harness (`scripts/live_byon_eval.py`) requires a running REAL stack (memory-service +
  Gateway) and therefore the external engine.

## What remains unreproducible without the external engine

- The GPU `87/87` D_Cortex real-text/semantic-QA audit and the FCE-M `runtime_proven` proof cannot be
  reproduced without the sealed v15.7a engine. The offline unit suite and the architecture/relational
  behavior remain fully reproducible; only the real-FCE-M-dependent milestone gates do not.
