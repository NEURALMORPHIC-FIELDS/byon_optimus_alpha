#!/usr/bin/env python
"""BYON Alpha App — one-command local web UI.

    python run_alpha_app.py        →  http://localhost:7860

REAL mode (default) routes every message through the BYON Gateway (→ BYON Optimus →
memory-service → D_Cortex + real FCE-M → Claude → BYON final audit). The app never
answers itself and never fabricates: if BYON is down you get ERROR, not a guess.

DEMO mode (opt-in, UI testing only):  BYON_ALPHA_DEMO_MODE=true python run_alpha_app.py
"""
from __future__ import annotations

import sys


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass  # .env is optional


def main() -> int:
    _load_dotenv()

    from app.local_config import AlphaConfig
    from app.runtime_manager import build_runtime, should_launch, startup_banner
    from app.alpha_ui import build_ui

    config = AlphaConfig.from_env()
    status = build_runtime(config)

    print(startup_banner(config, status), flush=True)
    launch, message = should_launch(config, status)
    print("-" * 60)
    print(message, flush=True)
    print("-" * 60, flush=True)

    if not launch:
        # REAL mode + Gateway unreachable + not allowed to show error-only UI.
        return 2

    demo = build_ui(config, status)
    print(f"Opening BYON Alpha UI at http://localhost:{config.ui_port}", flush=True)
    demo.launch(server_name=config.ui_host, server_port=config.ui_port,
                show_error=True, inbrowser=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
