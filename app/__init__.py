# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""BYON Alpha App - a runnable local web UI for chatting with BYON.

This is the human-facing front door: `python run_alpha_app.py` → http://localhost:7860.
It never decides truth - it only displays BYON's audited verdict. REAL mode calls the
BYON Gateway; DEMO mode (opt-in) returns clearly-labelled canned responses for UI testing.
"""
from __future__ import annotations

__version__ = "10.1.0-alpha"

__all__ = ["__version__"]
