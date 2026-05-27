# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Local configuration for the BYON Alpha App, resolved from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class AlphaConfig:
    gateway_url: str = "http://127.0.0.1:8090"
    memory_service_url: str = "http://127.0.0.1:8000"
    fcem_root: str = ""
    demo_mode: bool = False
    allow_error_ui: bool = False
    ui_port: int = 7860
    ui_host: str = "127.0.0.1"
    default_user_id: str = "lucian"
    default_session_id: str = "default"
    http_timeout_s: float = 60.0
    logs_dir: str = "runtime/alpha_app/logs"

    @classmethod
    def from_env(cls) -> "AlphaConfig":
        return cls(
            gateway_url=os.environ.get("BYON_GATEWAY_URL", "http://127.0.0.1:8090").rstrip("/"),
            memory_service_url=os.environ.get("BYON_MEMORY_SERVICE_URL", "http://127.0.0.1:8000").rstrip("/"),
            fcem_root=os.environ.get("FCEM_MEMORY_ENGINE_ROOT", ""),
            demo_mode=_truthy("BYON_ALPHA_DEMO_MODE", "false"),
            allow_error_ui=_truthy("BYON_ALPHA_ALLOW_ERROR_UI", "false"),
            ui_port=int(os.environ.get("BYON_ALPHA_UI_PORT", "7860") or 7860),
            ui_host=os.environ.get("BYON_ALPHA_UI_HOST", "127.0.0.1"),
            default_user_id=os.environ.get("BYON_ALPHA_DEFAULT_USER", "lucian"),
            default_session_id=os.environ.get("BYON_ALPHA_DEFAULT_SESSION", "default"),
            http_timeout_s=float(os.environ.get("BYON_ALPHA_HTTP_TIMEOUT_S", "60") or 60),
            logs_dir=os.environ.get("BYON_ALPHA_LOGS_DIR", "runtime/alpha_app/logs"),
        )

    @property
    def mode(self) -> str:
        return "DEMO" if self.demo_mode else "REAL"
