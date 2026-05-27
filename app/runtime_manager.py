# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Resolve runtime mode, build the right client, and check BYON Gateway health.

REAL mode is the default and calls the BYON Gateway. DEMO mode is opt-in and returns
canned, clearly-labelled responses (UI testing only). If the Gateway is unreachable in
REAL mode, startup refuses unless BYON_ALPHA_ALLOW_ERROR_UI=true - it never silently
pretends BYON is up.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .byon_runtime_client import BYONRuntimeClient, DemoBYONClient
from .local_config import AlphaConfig


@dataclass
class RuntimeStatus:
    mode: str                  # REAL | DEMO
    gateway_reachable: bool
    health: Dict[str, Any]
    client: Any


def build_runtime(config: AlphaConfig) -> RuntimeStatus:
    if config.demo_mode:
        client = DemoBYONClient()
        return RuntimeStatus(mode="DEMO", gateway_reachable=True,
                             health=client.health(), client=client)
    client = BYONRuntimeClient(config.gateway_url, config.http_timeout_s)
    health = client.health()
    return RuntimeStatus(mode="REAL", gateway_reachable=bool(health.get("_reachable")),
                         health=health, client=client)


def startup_banner(config: AlphaConfig, status: RuntimeStatus) -> str:
    lines = [
        "BYON Alpha App",
        f"Mode: {status.mode}",
        f"Gateway URL: {config.gateway_url}",
        f"Memory URL: {config.memory_service_url}",
        f"FCE-M root: {config.fcem_root or '(not set)'}",
        f"UI URL: http://localhost:{config.ui_port}",
    ]
    return "\n".join(lines)


def should_launch(config: AlphaConfig, status: RuntimeStatus) -> tuple[bool, str]:
    """Decide whether to launch the UI and return (launch, message)."""
    if status.mode == "DEMO":
        return True, "DEMO MODE - NOT REAL BYON RUNTIME (UI testing only)."
    if status.gateway_reachable:
        return True, "BYON Gateway reachable - REAL mode."
    msg = ("BYON Gateway not reachable.\n"
           "Start BYON runtime first (memory-service + orchestrator + Gateway),\n"
           "or enable BYON_ALPHA_DEMO_MODE=true for a UI-only demo.")
    if config.allow_error_ui:
        return True, msg + "\n(Launching UI anyway because BYON_ALPHA_ALLOW_ERROR_UI=true; chat will return ERROR.)"
    return False, msg
