# Cycle 14 - memory-service crash root-cause investigation

Committed analysis. The diagnostic scripts write their generated reports to the gitignored
`runtime/diagnostics/` (live_stack_health, memory_service_crash_report, crash_repro_report); this
document is the durable root-cause writeup.

FULL_LEVEL3_NOT_DECLARED preserved.

## Observed symptom (field)
Under sustained live-harness load, the memory-service on :8000 dies mid-run while the Gateway on
:8090 stays alive. This made live PASS untrustworthy.

## Reproduction commands
- `python scripts/reproduce_memory_service_crash.py --mode mixed`
- `python scripts/reproduce_memory_service_crash.py --mode acquisition-store`  (current 13.3 surface)
- live sustained load: 240 iterations of interleaved memory-service `search` + `store_batch`
  (batched writes) against a running memory-service.

## Investigation order and findings

### 0. SUBPROCESS STDOUT/STDERR PIPE-BUFFER DEADLOCK (prime suspect) - EXCLUDED for the launch path, mechanism CONFIRMED
- Evidence (code inspection): every place that launches the memory-service redirects the child's
  output to an OPEN FILE HANDLE, never to an unread `subprocess.PIPE`:
  - `app/service_supervisor.py` `start()`: `subprocess.Popen(..., stdout=log_file, stderr=...)`
    (file handle; separate stdout/stderr files as of Cycle 14).
  - `orchestration/integrate.py` `start_memory_service()`: `Popen(..., stdout=log_f, stderr=STDOUT)`
    (file handle).
  - All other `subprocess.PIPE` uses in owned code are `subprocess.run(..., timeout=...)`, which
    drains the pipes concurrently via `communicate()` (no deadlock).
- Conclusion: the canonical launch path is ALREADY pipe-safe. The S5-prescribed fix (file-handle
  redirection) was already present and is now hardened (separate stdout/stderr logs, process
  diagnostics, exit-code capture, bounded opt-in autorestart).
- Mechanism positively proven (test `test_unread_pipe_blocks_heavy_logger_but_file_handle_does_not`):
  a child writing > 1 MB to stdout BLOCKS (deadlocks) when stdout is an unread `subprocess.PIPE`,
  but COMPLETES (rc 0) when stdout is a file handle. This is exactly the "child dies/stalls mid-run
  while parent stays up" symptom, and file-handle redirection is the cure. The symptom is fully
  consistent with an unread-PIPE launch; the canonical path does not use one.

### A-E request patterns (search / relation / lifeloop / store-read / mixed)
- Live sustained load: 240 iterations of mixed `search` + `store_batch` against the running
  memory-service produced 0 crashes; `memory_service_alive_end == true`; elapsed ~37s. The real
  external FCE-M v15.7a runtime was loaded (`memory_engine_runtime: EXTERNAL v15.7a runtime loaded
  from .../13_v15_7a_consolidation, shim_used=False`), with 14072 facts in FAISS + FCE-M enabled.

### F memory growth / G file-descriptor leak
- Resource time-series sampling is implemented (`scripts/monitor_memory_service.py`, RSS/CPU/FD
  trajectory). In this environment `psutil` is not installed, so the live RSS/FD trend is honestly
  marked unavailable rather than fabricated. The 240-iteration run showed no crash and a stable
  alive-end, i.e. no abrupt failure; a longer psutil-backed run is the way to characterize any slow
  leak and is left as an operational follow-up (the monitor is ready for it).

### H FAISS metadata mismatch / I tombstone / J FCE-M external runtime / K supervision / L concurrency
- Not reproduced under the 240-iteration load. The external v15.7a runtime loaded cleanly. No
  evidence of crash under the tested patterns.

## Root cause / best diagnosis
- The reported symptom (child dies mid-run while the parent stays up under sustained logging) is
  the textbook unread-`subprocess.PIPE` buffer deadlock, which is positively reproduced here as a
  mechanism. The canonical BYON launch path does NOT use an unread PIPE (it uses file handles), so
  under the pipe-safe launch the memory-service sustained 240 iterations of mixed load with 0
  crashes. Where the historical crash was observed, an unread-PIPE capture of the child output is
  the most consistent cause; the in-repo launch path is already immune and is now further hardened.

## Whether a fix is applied; in-repo vs sealed
- Fix is IN-REPO and on the supervisor/Gateway side only (the sealed engine was NOT modified):
  pipe-safe file-handle redirection (confirmed + hardened with separate logs), process diagnostics
  (PID/command/redacted-env/exit-code), bounded opt-in autorestart (default OFF; any restart marks
  the run unstable), a pre-flight stack health check, a crash monitor with resource time-series, a
  crash-reproduction tool, a live-harness service-crash guard, and Gateway degraded-state behavior.

## Remaining risk
- If a future crash originates INSIDE the sealed external engine (FAISS/FCE-M internals) under load
  not covered by the 240-iteration test, that is engine-internal and out of scope to patch; the
  instrumentation will attribute it to MEMORY_SERVICE_CRASH honestly and the monitor's resource
  trajectory (with psutil present) will show whether it is a gradual leak or a sudden spike.
