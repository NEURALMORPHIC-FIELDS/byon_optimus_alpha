# BYON + D_Cortex - Windows convenience runner.
# Usage:  .\run.ps1 tests | smoke | integrate | e2e | v10
param([Parameter(Position=0)][string]$task = "tests")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

switch ($task) {
    "tests" {
        python -m pytest tests/ -m "not slow and not live" -v
    }
    "smoke" {
        # off-Colab D_Cortex audit, fast, real-text skipped (synthetic + chronodynamic)
        $env:DCORTEX_V99_OUTPUT_DIR = "$PSScriptRoot/runtime/dcortex_out"
        $env:D_CORTEX_FAST_RUN_REQUESTED = "true"
        $env:D_CORTEX_SKIP_REAL_TEXT = "true"
        Push-Location runtime/dcortex_run
        python "$PSScriptRoot/dcortex/v99_source.py"
        Pop-Location
    }
    "integrate" {
        # full-organism: boot memory-service + inject D_Cortex (no npm, no E2E)
        python orchestration/integrate.py --skip-pip --skip-npm --skip-e2e
    }
    "e2e" {
        # full-organism + live Claude QA gating harness (needs ANTHROPIC_API_KEY)
        python orchestration/integrate.py --skip-pip --skip-npm
    }
    "v10" {
        python -m dcortex.v10_developmental_loop --sessions 3 --fast
    }
    default {
        Write-Host "Unknown task '$task'. Use: tests | smoke | integrate | e2e | v10"
        exit 1
    }
}
