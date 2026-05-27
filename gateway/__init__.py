# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""BYON World Connector - Gateway (v10.1 alpha).

A stable, controlled API port between the outside world (web UIs, messaging
channels, automation) and the BYON Optimus organism. The Gateway never decides
truth: it routes every request through BYON, which is the sole epistemic
authority, and returns BYON's verdict (KNOWN / UNKNOWN / DISPUTED / REFUSED /
ERROR) verbatim.

Hard invariants (preserved from the development sheet and v10 milestone):
- No raw memory-service / D_Cortex / FCE-M / FAISS endpoint is exposed.
- Every message gets an audit trace.
- user_id + session_id are mandatory; memory is per-user isolated.
- No answer reaches a user unless BYON's final audit passed.
- UNKNOWN-when-ungrounded is never weakened; the Gateway fabricates nothing.
- FULL_LEVEL3_NOT_DECLARED preserved.
"""
from __future__ import annotations

__version__ = "10.1.0-alpha"

__all__ = ["__version__"]
