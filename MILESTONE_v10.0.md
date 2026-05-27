# Milestone tag - `v10.0-longitudinal-generalization-isolation`

**Status:** `V10_LONGITUDINAL_VALIDATED` · **8/8** · `FULL_LEVEL3_NOT_DECLARED`

v10.0 - Longitudinal Generalization & Isolation validates the integrated BYON + D_Cortex +
real FCE-M organism against eight standing gates designed to falsify audit-overfitting:
mandatory real FCE-M, unseen-domain transfer, real OOV UNKNOWN behaviour, delayed recall after
restart/interference, cross-user isolation, real-document contradiction streams, measurable
FCE-M advisory effect, and zero false assertions on ungrounded queries. The milestone passes
**8/8** on local CPU. It is a **controlled validation milestone - not a Level-3 claim and not
production-deployment proof.**

## Verified invariants (the architecturally decisive results)
- **0 false assertions on ungrounded queries** (0 / 12 sampled)
- **cross-user contamination = 0**
- **real FCE-M mandatory** (sealed v15.7a; shim/missing engine fails hard)
- **UNKNOWN on real OOV** (never-taught keys → UNKNOWN, no prior reconstruction)
- **delayed recall survives restart + interference** (retention 1.0)

## Provenance
- Verdict: `V10_LONGITUDINAL_VALIDATED` (gates 8 / 8)
- Real FCE-M: `adapter=DCortexAdapter`, `version=0.1.0-extracted-from-v15.7a-sealed-2026-04-26`
- Report: `runtime/v10_milestone_out/v10_milestone_report.json`
  - `sha256 = b0ef524d15f4064f41c05950c762f69eadf74df26e2cf2460f8b03fd9697a9bf`
  - (recompute: `python -c "import hashlib;print(hashlib.sha256(open('runtime/v10_milestone_out/v10_milestone_report.json','rb').read()).hexdigest())"`)
- Package: `byon-dcortex==10.0.0`
- Tests: full suite **15/15**; v10 milestone **8/8**

## Reproduce / validate
```powershell
python -m dcortex.v10_milestone --fast                       # produce the report
# release validation - a missing real FCE-M engine FAILs (never skips):
$env:BYON_VALIDATE_REAL_FCEM="true"; python -m pytest tests/test_v10_milestone.py -m slow -v
```

## Git tag (optional)
This product directory is not yet a git repository. To make this a real, signed tag:
```powershell
git init; git add -A; git commit -m "v10.0 - Longitudinal Generalization & Isolation (8/8)"
git tag -a v10.0-longitudinal-generalization-isolation -m "V10_LONGITUDINAL_VALIDATED 8/8, false_assertions=0, FULL_LEVEL3_NOT_DECLARED"
```

---

**Closed. Do not modify this milestone.** Next: **v10.1 - External Longitudinal Challenge**
(external document streams, real temporal gaps, larger namespace, adversarial paraphrase,
FCE-M decision influence on ranking/routing, provider-agnostic, signed memory ledger).
