# Contributing

Thanks for working on **BYON Optimus + D_Cortex**. This is a research prototype with a
strict epistemic and failure discipline - please keep contributions inside those rules.

## Ground rules (from the development sheet)

- **BYON Optimus is the orchestrator / epistemic auditor.** D_Cortex is an *additive*
  memory organ, never a replacement for BYON.
- **Coexistence, not contest.** Classic (transformer/GRU) and morphogenetic faculties
  meet in memory. Never frame a result as one faculty "beating" another; the decisive
  question is *"is the answer grounded?"*.
- **Epistemic Memory Contract.** Without valid committed memory, the system answers
  `UNKNOWN` - it must not reconstruct from prior.
- **No diluted fallback (§7.3).** Missing real components fail hard with a clear message.
  Skipped heavy stages are tagged `skipped: true` and never counted as passing.
- **Bounded claims (§8).** Not a general LLM, not consciousness, not a finished product;
  `FULL_LEVEL3_NOT_DECLARED` is preserved. Don't overclaim in code, tests, or docs.

## Development setup

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e .[dev]            # editable install + pytest/cov
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Node 18+ is needed for the orchestrator build and the live E2E harness.

## Tests and validation profiles

```powershell
# fast, offline, no training/network
python -m pytest tests/ -m "not slow and not live"

# release validation - real FCE-M v15.7a mandatory (missing engine ⇒ FAIL, not skip)
$env:FCEM_MEMORY_ENGINE_ROOT="<path-to>/13_v15_7a_consolidation"
$env:BYON_VALIDATE_REAL_FCEM="true"
python -m pytest tests/test_v10_milestone.py -m slow -v
```

- **Unit-portable profile (default):** engine-dependent tests `skip` when the v15.7a
  engine is not locally resolvable, so the fast suite stays green offline.
- **Release-validation profile:** `BYON_VALIDATE_REAL_FCEM=true` turns a missing real
  engine into a hard failure. Use this before tagging a milestone.

## Pull requests

- Keep changes scoped; match the surrounding code's style and comment density.
- Add or update tests for behaviour you change. Report measured results, including
  negative ones - don't hide a failing gate.
- Never commit secrets. `secrets/`, `external/`, `runtime/`, `.env` are gitignored;
  scan staged changes for `sk-ant-` before pushing (see `SECURITY.md`).
- Validated milestones are closed; do not silently modify a tagged milestone's logic.
