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
    ap.add_argument("--local-dev", action="store_true",
                    help="dev only: allow the in-repo LocalBYONBackend instead of memory-service")
    ap.add_argument("--save-key", action="store_true", help="persist ANTHROPIC_API_KEY to .env.local")
    ap.add_argument("--no-prompt", action="store_true", help="never prompt for secrets")
    ap.add_argument("--train-self", action="store_true",
                    help="ingest the canonical repo corpus into memory before running")
    ap.add_argument("--vault", default="", help="path to an Obsidian vault to train on")
    ap.add_argument("--train-vault", action="store_true", help="ingest the --vault corpus before running")
    ap.add_argument("--then-run", action="store_true", help="launch the UI after training")
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
    child_env["BYON_GATEWAY_PORT"] = str(gw_port)
    gateway_url = f"http://{host}:{gw_port}"

    # --- start the canonical memory-service (FAISS + FCE-M + trust tiers) ----
    # REAL mode is CANONICAL ONLY: memory-service is mandatory. LocalBYONBackend is
    # forbidden here — it exists solely for --demo / --local-dev. No silent fallback.
    memory_url = "http://127.0.0.1:8000"
    if disc.memory_service_server is None:
        _print("-" * 60)
        _print("REAL mode requires the canonical memory-service (FAISS + FCE-M + trust tiers),")
        _print("but its server.py was not found in the checkout.")
        _print("Fix: stage external/byon_optimus, or use --local-dev (non-canonical) / --demo.")
        _print("-" * 60)
        return 2

    _print("Starting memory-service (FAISS + FCE-M + trust tiers)...")
    ms_env = dict(os.environ)
    ms_env["MEMORY_SERVICE_HOST"] = "127.0.0.1"
    ms_env["MEMORY_SERVICE_PORT"] = "8000"
    ms_env["FCEM_MEMORY_ENGINE_ROOT"] = disc.fcem_root
    sup.start("memory-service", [sys.executable, "server.py"],
              cwd=str(disc.memory_service_server.parent), env=ms_env)
    if not sup.wait_http("memory-service", f"{memory_url}/health", timeout=90):
        _print("-" * 60)
        _print("memory-service failed to become healthy. REAL mode does NOT fall back to a")
        _print("fake/local backend — exiting. Last log lines:")
        _print(sup.tail_log("memory-service"))
        _print("-" * 60)
        if args.local_dev:
            _print("  (--local-dev set: continuing with non-canonical LocalBYONBackend)")
        else:
            sup.stop_all()
            return 2
    from gateway.memory_service_client import MemoryServiceClient
    mc = MemoryServiceClient(memory_url)
    warm = any(mc.embedder_warm() or time.sleep(1) for _ in range(60))
    _print(f"  memory-service: OK (embedder {'warm' if warm else 'warming'})")
    backend_mode = "local" if args.local_dev and not mc.health().get("_reachable") else "memory_service"
    child_env["BYON_MEMORY_SERVICE_URL"] = memory_url
    child_env["BYON_BACKEND_MODE"] = backend_mode
    _print(f"  backend mode: {backend_mode}  (canonical = memory_service)")

    # --- optional training BEFORE the UI: corpus + vault through the canonical pipeline ---
    if args.train_self:
        _print("Self-training on the canonical repo corpus...")
        from gateway.self_training import train_self
        rep = train_self(memory_url, repo_root=disc.repo_root)
        _print(f"  self-train: {rep.get('chunks_stored', 0)} chunks from {rep.get('files', 0)} files; "
               f"consolidate={rep.get('consolidated')}")
    if args.train_vault and args.vault:
        _print(f"Training on Obsidian vault: {args.vault} ...")
        from gateway.vault_training import train_vault
        rep = train_vault(memory_url, vault_path=args.vault)
        _print(f"  vault-train: {rep.get('chunks_stored', 0)} chunks from {rep.get('files', 0)} notes; "
               f"backlinks={rep.get('backlinks', 0)}; consolidate={rep.get('consolidated')}")

    _print("Starting BYON Gateway (epistemic search + canonical memory-service)...")
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

    if (args.train_self or args.train_vault) and not args.then_run:
        _print("Training complete. (pass --then-run to also open the UI)")
        sup.stop_all()
        return 0

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
