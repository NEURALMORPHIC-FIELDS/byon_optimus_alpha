"""Pytest fixtures for the BYON + D_Cortex harness."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEVEL3_REPO = PROJECT_ROOT / "runtime" / "dcortex_run" / "byon_optimus_level3_real_source"

# make the package importable without installation
sys.path.insert(0, str(PROJECT_ROOT))

# Pin the fast, off-Colab configuration at conftest IMPORT time - before any test module
# is collected. dcortex.v99_source reads D_CORTEX_FAST_RUN_REQUESTED at import time to build
# its module-level config `C`, so a test that imports it (directly or via v10_milestone) at
# collection time must already see fast_run=true. The autouse fixture below keeps parity for
# anything that inspects the env during a test.
os.environ.setdefault("D_CORTEX_FAST_RUN_REQUESTED", "true")
os.environ.setdefault("D_CORTEX_SKIP_REAL_TEXT", "true")
if LEVEL3_REPO.exists():
    os.environ.setdefault("DCORTEX_LEVEL3_REPO_DIR", str(LEVEL3_REPO))


@pytest.fixture(scope="session", autouse=True)
def _fast_env() -> None:
    """Pin a fast, off-Colab configuration for the whole test session."""
    os.environ.setdefault("D_CORTEX_FAST_RUN_REQUESTED", "true")
    os.environ.setdefault("D_CORTEX_SKIP_REAL_TEXT", "true")
    if LEVEL3_REPO.exists():
        os.environ.setdefault("DCORTEX_LEVEL3_REPO_DIR", str(LEVEL3_REPO))


@pytest.fixture(scope="session")
def level3_available() -> bool:
    return (LEVEL3_REPO / "byon-orchestrator" / "level3-research" / "schemas" / "memory_event.py").exists()
