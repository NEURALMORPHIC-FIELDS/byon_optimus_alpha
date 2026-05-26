#!/usr/bin/env python
"""BYON — one-command local runtime launcher.

    python run_byon.py            # REAL FULL mode: starts everything + opens the UI
    python run_byon.py --connect  # connect to an already-running Gateway, UI only
    python run_byon.py --demo     # fake UI testing only (NOT real BYON)

REAL FULL mode starts the BYON Gateway (with the real in-repo D_Cortex epistemic backend +
real FCE-M v15.7a advisory) as a managed child process, then opens the web UI at
http://localhost:7860. The user does NOT start the Gateway / memory-service / UI by hand.

Chat path: UI -> BYONRuntimeClient -> Gateway /v1/chat -> real BYON backend
           (D_Cortex grounding + epistemic contract + real FCE-M + optional Claude language)
           -> BYON final audit -> normalized response -> UI. No direct Claude/D_Cortex/
           memory-service calls from the UI. If the backend fails: ERROR, never fabrication.
"""
from __future__ import annotations

import argparse
import os
import sys
import time


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
        load_dotenv(".env.local", override=True)
    except Exception:
        pass


def _print(*a):
    print(*a, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="BYON one-command local runtime")
    ap.add_argument("--connect", action="store_true", help="connect to an existing Gateway (UI only)")
    ap.add_argument("--demo", action="store_true", help="fake UI testing only (not real BYON)")
    ap.add_argument("--save-key", action="store_true", help="persist ANTHROPIC_API_KEY to .env.local")
    ap.add_argument("--no-prompt", action="store_true", help="never prompt for secrets")
    args = ap.parse_args()

    _load_dotenv()

    from app.local_config import AlphaConfig
    from app.runtime_discovery import discover
    from app.service_supervisor import ServiceSupervisor, is_port_free, find_free_port
    from app.health_checks import gateway_health
    from app.secret_prompt import ensure_api_key, mask

    config = AlphaConfig.from_env()
    mode = "DEMO" if args.demo else ("CONNECT" if args.connect else "REAL")

    _print("BYON Local Runtime")
    _print(f"  Mode: {mode}")

    # ---------------- DEMO ----------------
    if mode == "DEMO":
        os.environ["BYON_ALPHA_DEMO_MODE"] = "true"
        return _launch_ui_only(config, demo=True)

    # ---------------- CONNECT ----------------
    if mode == "CONNECT":
        _print(f"  Gateway URL: {config.gateway_url}")
        _print("Checking gateway health...")
        h = gateway_health(config.gateway_url)
        if not h.get("_reachable"):
            _print("-" * 60)
            _print(f"BYON Gateway not reachable at {config.gateway_url}.")
            _print("Start it (or run without --connect for REAL full mode).")
            _print("-" * 60)
            return 2
        _print("  Gateway: OK")
        return _launch_ui_only(config, demo=False)

    # ---------------- REAL FULL ----------------
    _print("Checking environment...")
    disc = discover()
    if not disc.fcem_root:
        _print("-" * 60)
        for p in disc.problems:
            _print(f"  MISSING: {p}")
        _print("  In REAL FULL mode the real FCE-M engine is required (no shim).")
        _print("  Fix: set FCEM_MEMORY_ENGINE_ROOT, or use --demo for UI-only testing.")
        _print("-" * 60)
        return 2
    os.environ["FCEM_MEMORY_ENGINE_ROOT"] = disc.fcem_root
    os.environ["FSOAT_REQUIRE_EXTERNAL_FCEM_RUNTIME"] = "true"
    _print(f"  Real FCE-M engine: {disc.fcem_root}")
    _print(f"  Memory-service server: {disc.memory_service_server or '(not found — using in-repo D_Cortex backend)'}")

    # Secret: Claude is optional (language only). Prompt if missing unless suppressed.
    key = ensure_api_key(interactive=not args.no_prompt, save=args.save_key)
    _print(f"  Claude key: {'PRESENT ' + mask(key) if key else 'MISSING (will run without Claude language; grounding still works)'}")

    # Resolve the Gateway port (reuse a healthy one, else pick a free port).
    host = "127.0.0.1"
    gw_port = config_port_from_url(config.gateway_url, default=8090)
    if not is_port_free(host, gw_port):
        existing = gateway_health(f"http://{host}:{gw_port}")
        if existing.get("_reachable"):
            _print(f"  Gateway already healthy on :{gw_port} — reusing it.")
            os.environ["BYON_GATEWAY_URL"] = f"http://{host}:{gw_port}"
            return _launch_ui_only(AlphaConfig.from_env(), demo=False)
        gw_port = find_free_port(host, gw_port + 1)
        _print(f"  Port busy — using gateway port :{gw_port} instead.")

    sup = ServiceSupervisor()
    child_env = dict(os.environ)
    child_env["BYON_BACKEND_MODE"] = "local"          # real in-repo D_Cortex + real FCE-M
    child_env["BYON_GATEWAY_PORT"] = str(gw_port)
    gateway_url = f"http://{host}:{gw_port}"

    _print("Starting BYON Gateway (real D_Cortex epistemic backend + real FCE-M)...")
    sup.start("gateway", [sys.executable, "-m", "gateway.server"],
              cwd=str(disc.repo_root), env=child_env)
    ok = sup.wait_http("gateway", f"{gateway_url}/v1/health", timeout=60)
    if not ok:
        _print("-" * 60)
        _print("BYON Gateway failed to become healthy. Last log lines:")
        _print(sup.tail_log("gateway"))
        _print("-" * 60)
        sup.stop_all()
        return 2
    _print("  Gateway: OK")

    os.environ["BYON_GATEWAY_URL"] = gateway_url
    _print("Starting Alpha UI...")
    try:
        return _launch_ui_only(AlphaConfig.from_env(), demo=False)
    finally:
        _print("Shutting down BYON services...")
        sup.stop_all()


def config_port_from_url(url: str, default: int) -> int:
    try:
        return int(url.rstrip("/").rsplit(":", 1)[1])
    except Exception:
        return default


def _launch_ui_only(config, demo: bool) -> int:
    """Build the runtime client + UI and launch Gradio. Shared by all modes."""
    from app.runtime_manager import build_runtime, should_launch
    from app.alpha_ui import build_ui

    if demo:
        os.environ["BYON_ALPHA_DEMO_MODE"] = "true"
    status = build_runtime(config)
    launch, message = should_launch(config, status)
    _print("Ready." if launch else "Not ready.")
    _print(message)
    if not launch:
        return 2
    demo_app = build_ui(config, status)
    url = f"http://localhost:{config.ui_port}"
    _print(f"Open: {url}")
    demo_app.launch(server_name=config.ui_host, server_port=config.ui_port,
                    show_error=True, inbrowser=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
