# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""HTTP client onto the BYON Gateway used by the MCP tools.

Every MCP tool goes through this client, i.e. through the Gateway's controlled v1
surface - never the raw memory-service. Tests bind it to the FastAPI app via an
ASGI transport so the full MCP→Gateway path is exercised without a network port.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class GatewayClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8090",
                 http_client: Optional[Any] = None, timeout_s: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._client = http_client  # inject an httpx.Client (e.g. ASGI transport) in tests

    def _client_or_new(self):
        if self._client is not None:
            return self._client, False
        import httpx
        return httpx.Client(base_url=self.base_url, timeout=self.timeout_s), True

    def _request(self, method: str, path: str, **kw) -> Dict[str, Any]:
        client, owned = self._client_or_new()
        try:
            if owned:  # real httpx.Client we created → honour timeout
                resp = client.request(method, f"{self.base_url}{path}", timeout=self.timeout_s, **kw)
            else:      # injected client (e.g. Starlette TestClient) → no timeout kwarg
                resp = client.request(method, path, **kw)
            resp.raise_for_status()
            return resp.json()
        finally:
            if owned:
                client.close()

    def chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/v1/chat", json=payload)

    def memory_status(self, user_id: str) -> Dict[str, Any]:
        return self._request("GET", "/v1/memory/status", params={"user_id": user_id})

    def feedback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/v1/feedback", json=payload)

    def forget(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/v1/forget", json=payload)

    def audit_trace(self, trace_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/audit/{trace_id}")
