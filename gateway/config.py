"""Gateway configuration, resolved from environment with safe alpha defaults.

Every flag has a conservative default: external connectors are OFF, the final
BYON audit is REQUIRED, per-user namespaces are REQUIRED, and direct
memory-service exposure is FORBIDDEN. These are the safety posture of the
v10.1 alpha and must not be silently weakened.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class GatewayConfig:
    gateway_port: int = 8090
    memory_service_url: str = "http://127.0.0.1:8000"
    orchestrator_url: str = "http://127.0.0.1:3000"
    alpha_mode: bool = True
    require_final_audit: bool = True
    require_user_namespace: bool = True
    allow_direct_memory_service: bool = False
    enable_mcp: bool = True
    enable_librechat: bool = True
    enable_openclaw: bool = False
    enable_n8n: bool = False
    kill_switch: bool = False
    users_root: str = "runtime/users"
    audit_root: str = "runtime/v10_1_out/audit"
    rate_limit_per_min: int = 60
    backend_timeout_s: float = 60.0

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        return cls(
            gateway_port=_int("BYON_GATEWAY_PORT", 8090),
            memory_service_url=os.environ.get("BYON_MEMORY_SERVICE_URL", "http://127.0.0.1:8000"),
            orchestrator_url=os.environ.get("BYON_ORCHESTRATOR_URL", "http://127.0.0.1:3000"),
            alpha_mode=_truthy("BYON_ALPHA_MODE", "true"),
            require_final_audit=_truthy("BYON_REQUIRE_FINAL_AUDIT", "true"),
            require_user_namespace=_truthy("BYON_REQUIRE_USER_NAMESPACE", "true"),
            allow_direct_memory_service=_truthy("BYON_ALLOW_DIRECT_MEMORY_SERVICE", "false"),
            enable_mcp=_truthy("BYON_ENABLE_MCP", "true"),
            enable_librechat=_truthy("BYON_ENABLE_LIBRECHAT", "true"),
            enable_openclaw=_truthy("BYON_ENABLE_OPENCLAW", "false"),
            enable_n8n=_truthy("BYON_ENABLE_N8N", "false"),
            kill_switch=_truthy("BYON_KILL_SWITCH", "false"),
            users_root=os.environ.get("BYON_USERS_ROOT", "runtime/users"),
            audit_root=os.environ.get("BYON_AUDIT_ROOT", "runtime/v10_1_out/audit"),
            rate_limit_per_min=_int("BYON_RATE_LIMIT_PER_MIN", 60),
            backend_timeout_s=float(_int("BYON_BACKEND_TIMEOUT_S", 60)),
        )
