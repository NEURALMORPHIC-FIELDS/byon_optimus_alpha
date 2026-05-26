"""Thin HTTP client for the canonical BYON memory-service.

This is glue, not a new memory system. It speaks the existing memory-service action API
(`store` / `search` / `verified_fact_add` / `fce_consolidate` / `fce_assimilate_receipt` …)
so the epistemic search reuses BYON's real FAISS semantic memory + FCE-M consolidation +
trust tiers (VERIFIED_PROJECT_FACT / DOMAIN_VERIFIED / USER_PREFERENCE / DISPUTED_OR_UNSAFE)
instead of a parallel store.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class MemoryServiceClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout_s: float = 30.0,
                 http_client: Optional[Any] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._client = http_client  # injected in tests

    def _act(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._client is not None:
            resp = self._client.request("POST", "/", json=payload)
        else:
            import httpx
            with httpx.Client(base_url=self.base_url, timeout=self.timeout_s) as c:
                resp = c.request("POST", "/", json=payload)
        if getattr(resp, "status_code", 200) >= 400:
            return {"success": False, "error": f"HTTP {resp.status_code}"}
        return resp.json()

    # -- health / warmup -----------------------------------------------------
    def health(self) -> Dict[str, Any]:
        try:
            if self._client is not None:
                r = self._client.request("GET", "/health")
            else:
                import httpx
                with httpx.Client(base_url=self.base_url, timeout=5.0) as c:
                    r = c.request("GET", "/health")
            ok = getattr(r, "status_code", 500) == 200
            data = r.json() if ok else {}
            data["_reachable"] = ok
            return data
        except Exception as exc:
            return {"_reachable": False, "error": str(exc)}

    def embedder_warm(self) -> bool:
        """The production embedder loads lazily; a fact stored before it is warm gets a
        hash-fallback vector. Probe readiness by checking the embed model name."""
        try:
            e = self._act({"action": "embed", "text": "warmup"})
            return e.get("model") == "all-MiniLM-L6-v2"
        except Exception:
            return False

    # -- store / search (FAISS) ---------------------------------------------
    def store_fact(self, fact: str, *, source: str = "", tags: Optional[List[str]] = None,
                   thread_id: Optional[str] = None, trust: Optional[str] = None,
                   disputed: Optional[bool] = None, disputed_pattern: Optional[str] = None) -> Dict[str, Any]:
        return self._act({"action": "store", "type": "fact", "data": {
            "fact": fact, "source": source, "tags": tags or [], "thread_id": thread_id,
            "trust": trust, "disputed": disputed, "disputed_pattern": disputed_pattern}})

    def store_conversation(self, content: str, *, role: str = "user",
                           thread_id: Optional[str] = None) -> Dict[str, Any]:
        return self._act({"action": "store", "type": "conversation",
                          "data": {"content": content, "role": role, "thread_id": thread_id}})

    def search_facts(self, query: str, *, top_k: int = 5, threshold: float = 0.35,
                     thread_id: Optional[str] = None, scope: str = "global") -> List[Dict[str, Any]]:
        r = self._act({"action": "search", "type": "fact", "query": query, "top_k": top_k,
                       "threshold": threshold, "thread_id": thread_id, "scope": scope})
        return r.get("results", []) or []

    def search_conversation(self, query: str, *, top_k: int = 5, threshold: float = 0.4,
                            thread_id: Optional[str] = None, scope: str = "thread") -> List[Dict[str, Any]]:
        r = self._act({"action": "search", "type": "conversation", "query": query, "top_k": top_k,
                       "threshold": threshold, "thread_id": thread_id, "scope": scope})
        return r.get("results", []) or []

    # -- FCE-M consolidation / learning -------------------------------------
    def fce_consolidate(self) -> Dict[str, Any]:
        return self._act({"action": "fce_consolidate"})

    def fce_assimilate_receipt(self, order_id: str, status: str,
                               summary: Optional[str] = None) -> Dict[str, Any]:
        return self._act({"action": "fce_assimilate_receipt", "order_id": order_id,
                          "status": status, "summary": summary})

    def fce_advisory(self) -> Dict[str, Any]:
        return self._act({"action": "fce_advisory"})

    def stats(self) -> Dict[str, Any]:
        return self._act({"action": "stats"})
