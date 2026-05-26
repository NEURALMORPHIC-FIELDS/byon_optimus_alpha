"""BYON Optimus + D_Cortex — off-Colab, enterprise harness.

This package wraps the v9.9 Chronodynamic Semantic Grounded Cortex (``v99_source``)
so it can run outside Google Colab, on a local CPU/GPU machine, and be integrated
as an additive memory organ into the canonical BYON Optimus memory-service.

Design rules preserved from the development sheet:
  * BYON Optimus remains the orchestrator / epistemic auditor.
  * D_Cortex is an additive memory organ, never a replacement for BYON.
  * No diluted fallback: missing real components fail hard with a clear report.
"""

from __future__ import annotations

__version__ = "10.0.0"

__all__ = ["__version__"]
