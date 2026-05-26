"""Health checks for the launcher and the UI health panel."""
from __future__ import annotations

import os
from typing import Any, Dict


def gateway_health(gateway_url: str) -> Dict[str, Any]:
    import httpx
    try:
        r = httpx.get(f"{gateway_url.rstrip('/')}/v1/health", timeout=3.0)
        r.raise_for_status()
        data = r.json()
        data["_reachable"] = True
        return data
    except Exception as exc:
        return {"_reachable": False, "error": str(exc)}


def claude_key_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def summarize(gateway_url: str) -> Dict[str, str]:
    """Compact OK/FAIL panel for the UI."""
    h = gateway_health(gateway_url)
    if not h.get("_reachable"):
        return {"Gateway": "FAIL", "Memory/D_Cortex": "UNKNOWN", "FCE-M": "UNKNOWN",
                "Claude key": "PRESENT" if claude_key_present() else "MISSING"}
    backend = h.get("backend", {}) or {}
    fcem = backend.get("fcem", {}) or {}
    return {
        "Gateway": "OK",
        "Memory/D_Cortex": "OK" if backend.get("backend") else "UNKNOWN",
        "FCE-M": "REAL" if fcem.get("runtime_proven") else "NOT FOUND",
        "Claude key": "PRESENT" if (backend.get("claude", {}) or {}).get("key_present")
                      or claude_key_present() else "MISSING",
    }
