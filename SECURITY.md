# Security Policy

## Reporting a vulnerability

Please report security issues privately to the maintainers (open a private security
advisory on GitHub, or contact the NEURALMORPHIC-FIELDS organisation owners). Do not
open a public issue for anything that could expose a credential or a usable exploit.

## Secrets handling (hard rules)

- **API keys are never written to a tracked file.** The `ANTHROPIC_API_KEY` lives only in
  the process environment or in `secrets/anthropic.key`, and both `secrets/` and `.env`
  are gitignored. The live end-to-end harness receives the key only through the process
  environment.
- `external/` (third-party checkouts) and `runtime/` (outputs, logs, staged repos) are
  gitignored and must never be committed.
- Before any commit, scan the staged set for `sk-ant-` / `ANTHROPIC_API_KEY=` literals.

## Trust boundaries

- **BYON Optimus is the canonical epistemic auditor.** Answers are gated by the Epistemic
  Memory Contract: a value may be asserted only if it is anchored in valid, committed
  memory with provenance - otherwise the answer is `UNKNOWN`. Ungrounded reconstruction
  from prior is treated as a defect (the v10 milestone gates `FALSE_ASSERTION_RATE_ZERO`).
- The Executor runs air-gapped against signed `ExecutionOrder`s (Ed25519); the D_Cortex
  organ is **additive** and never overrides the trust hierarchy.
- The memory-trust boundary (FAISS / FCE-M / D_Cortex writes) is where provenance is
  enforced; treat any unsigned or unprovenanced write as untrusted input.

## Failure discipline (no diluted fallback - development sheet §7.3)

Missing real components must **fail hard** with a clear message, never silently degrade to
a stub or mock. Real FCE-M v15.7a is mandatory in release validation
(`BYON_VALIDATE_REAL_FCEM=true`), where a missing engine is a hard FAIL, not a skip.
