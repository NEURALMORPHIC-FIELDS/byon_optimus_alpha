# Cycle 14.1 - full-stack live validation (178-gate harness under psutil-backed monitor)

Committed summary. The raw artifacts (runtime/eval/live_byon_eval_report.json,
runtime/diagnostics/memory_service_crash_report.json, live_stack_health.json,
memory_service_process.json, runtime/logs/memory_service_*.log) stay gitignored under runtime/;
this document records the measured verdict. FULL_LEVEL3_NOT_DECLARED preserved.

## Run
- Stack launched via run_byon.py (pipe-safe file-handle child output); pre-flight
  scripts/check_live_stack.py exit 0 (Gateway :8090 + memory-service :8000, external FCE-M v15.7a
  runtime loaded, shim_used=false).
- psutil 7.2.2 active; crash monitor sampled the memory-service PID every 5s for the whole run.
- Harness: scripts/live_byon_eval.py (full configured set).

## Two runs (full transparency, not best-of-N)
- Run 1 (start 2026-05-29T00:36:40Z, end 00:54:57Z, 18.3 min): 178 graded, 177 pass, 1 FAIL.
  The single failure was `batch_write_status`, a STALE TEST ASSERTION: the gate checked
  `res.get("failed", 0) == 0`, but the Cycle 13.3 store_batch endpoint returns `failed` as a LIST,
  so an empty `failed: []` (no failures) was mis-read as a failure. Live probe confirmed the batch
  genuinely succeeded: `{success: True, stored: 3, ids: [3], failed: []}`. This is a test bug, not
  a system fault.
- Correction (not weakening): the assertion was fixed to `not res.get("failed")` (empty list OR 0
  both mean no failures). The Cycle 14 ServiceHealthGuard report-fields wiring was also completed
  so the eval report now carries stack_health_start/end, memory_service_crashed, last_successful_gate.
- Run 2 (re-run; start 2026-05-29T00:59:29Z, end 01:22:17Z, 22.8 min): 178 graded, 178 pass, 0 FAIL,
  all_pass=true.

## Pre-declared verdict P1-P5 (measured, re-run)

```json
[
  {"criterion_id": "P1_logical_all_gates_pass",
   "passed": true,
   "evidence": {"configured_graded": 178, "passed": 178, "failed": 0, "skipped": 4,
                "all_pass": true, "note": "run 1 was 177/178 on a stale batch_write_status assertion (batch actually succeeded); corrected; re-run 178/178"}},
  {"criterion_id": "P2_stability_no_crash_no_restart",
   "passed": true,
   "evidence": {"memory_service_alive_end": true, "memory_service_crashed": false,
                "first_failure_timestamp": null, "restarts": 0, "supervisor_unstable": false}},
  {"criterion_id": "P3_no_silent_fallback",
   "passed": true,
   "evidence": {"failure_categories": [], "all_statuses_epistemically_valid": true,
                "any_cross_user_leak": false, "any_objective_grounded_in_user_memory": false,
                "note": "no MEMORY_SERVICE_CRASH; source-bleed + no-fallback gates passed; no fabricated answer"}},
  {"criterion_id": "P4_resource_leak_gate",
   "passed": true,
   "evidence": {"rss_mb_start": 558.4, "rss_mb_end": 558.6, "rss_peak_mb": 567.4,
                "rss_ratio_end_over_start": 1.000, "rss_slope_mb_per_min": 0.0214,
                "fd_start": 4, "fd_end": 4, "fd_delta": 0, "fd_slope_per_min": 0.0,
                "samples": 184, "thresholds": "RSS ratio<=1.5, FD delta<=100, no monotonic rise"}},
  {"criterion_id": "P5_duration_real",
   "passed": true,
   "evidence": {"harness_elapsed_seconds": 1368, "harness_elapsed_min": 22.8,
                "monitor_uptime_seconds": 1391, "threshold_seconds": 300}}
]
```

## Verdict: PASS (all five criteria true)
Stability is now PROVEN under the real harness profile: a full 178-gate graded run over ~23 minutes,
with psutil-backed RSS/CPU/FD time-series, produced 0 crashes, 0 restarts, a flat memory/FD trend
(no leak), and 178/178 gate passes. A crash would have been reported as MEMORY_SERVICE_CRASH by the
ServiceHealthGuard; none occurred.

## Skipped gates (4, config-gated, not failures)
vault_error_report_exists_if_errors (no vault errors to report), compaction_apply_if_enabled
(needs BYON_EVAL_COMPACT_APPLY=1), failed_task_keeps_pressure (no failed task observed), and
adv_restart_recall (needs BYON_EVAL_RESTART_PHASE; the restart-recall gate is a two-phase
prepare/verify around a real restart).
