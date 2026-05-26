"""The boundary to the BYON Optimus organism.

The Gateway delegates the *decision* to BYON through a `BYONBackend`. The Gateway
itself never produces an answer. Two rules make this safe:

1. **Fail-hard, never fabricate.** If BYON is unreachable or errors, the backend
   returns an ERROR result with an empty answer — it does not invent a reply, fall
   back to a stub, or answer from any other source (dev-sheet §7.3).
2. **The organism owns the verdict.** answer + epistemic_status + grounding +
   dcortex/fcem summaries come from BYON. The Gateway only normalises and labels.

`HttpBYONBackend` is the production backend (calls the orchestrator). Tests inject
a deterministic in-memory backend via FastAPI dependency override — that is a test
double, not a production fallback; production wiring uses the HTTP backend only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class BYONResult(BaseModel):
    answer: str = ""
    epistemic_status: str = "ERROR"   # KNOWN | UNKNOWN | DISPUTED | REFUSED | ERROR
    grounded: bool = False
    final_audit_passed: bool = False
    has_valid_memory: bool = False
    sources: List[str] = Field(default_factory=list)
    provenance_required: bool = True
    memory_written: bool = False
    memory_keys: Optional[List[str]] = None
    dcortex: Optional[Dict[str, Any]] = None
    fcem: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@runtime_checkable
class BYONBackend(Protocol):
    def chat(self, *, user_id: str, session_id: str, channel: str, message: str,
             namespace_dir: Path) -> BYONResult: ...

    def memory_status(self, *, user_id: str, namespace_dir: Path) -> Dict[str, Any]: ...

    def forget(self, *, user_id: str, namespace_dir: Path) -> Dict[str, Any]: ...


class HttpBYONBackend:
    """Calls the real BYON Optimus orchestrator over HTTP. On any failure it returns
    an ERROR result (no answer) — the Gateway then refuses, it never fabricates."""

    def __init__(self, orchestrator_url: str, timeout_s: float = 60.0) -> None:
        self.base = orchestrator_url.rstrip("/")
        self.timeout_s = timeout_s

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        import httpx  # local import so importing this module never requires httpx
        url = f"{self.base}{path}"
        resp = httpx.post(url, json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def chat(self, *, user_id: str, session_id: str, channel: str, message: str,
             namespace_dir: Path) -> BYONResult:
        try:
            data = self._post("/byon/chat", {
                "user_id": user_id, "session_id": session_id, "channel": channel,
                "message": message, "namespace_dir": str(namespace_dir),
            })
        except Exception as exc:  # connection refused, timeout, non-2xx, bad JSON
            return BYONResult(epistemic_status="ERROR", grounded=False,
                              final_audit_passed=False,
                              error=f"BYON orchestrator unreachable/failed: {exc}")
        # Trust only fields BYON returns; default to the safe (ungrounded) side.
        return BYONResult(
            answer=str(data.get("answer", "")),
            epistemic_status=str(data.get("epistemic_status", "ERROR")),
            grounded=bool(data.get("grounded", False)),
            final_audit_passed=bool(data.get("final_audit_passed", False)),
            has_valid_memory=bool(data.get("has_valid_memory", False)),
            sources=list(data.get("sources", []) or []),
            provenance_required=bool(data.get("provenance_required", True)),
            memory_written=bool(data.get("memory_written", False)),
            memory_keys=data.get("memory_keys"),
            dcortex=data.get("dcortex"),
            fcem=data.get("fcem"),
        )

    def memory_status(self, *, user_id: str, namespace_dir: Path) -> Dict[str, Any]:
        try:
            return self._post("/byon/memory_status",
                              {"user_id": user_id, "namespace_dir": str(namespace_dir)})
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def forget(self, *, user_id: str, namespace_dir: Path) -> Dict[str, Any]:
        try:
            return self._post("/byon/forget",
                              {"user_id": user_id, "namespace_dir": str(namespace_dir)})
        except Exception as exc:
            return {"forgotten": False, "error": str(exc)}
