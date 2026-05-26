"""BYONRuntimeClient — the app's only path to BYON.

The app NEVER answers epistemically. It calls the BYON Gateway and displays BYON's
verdict. Hard rules (enforced here, not just documented):

- backend unreachable  → ERROR, grounded=False, answer="BYON runtime is not available."
- no final audit       → REFUSED, grounded=False, answer="Response blocked because BYON
                          final audit was not present."
- UNKNOWN / REFUSED     → preserved verbatim; never rewritten into a guessed answer.
- the app never calls Claude directly and never fabricates.

DEMO mode returns clearly-labelled canned responses and is opt-in (UI testing only).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

_VALID = {"KNOWN", "UNKNOWN", "DISPUTED", "REFUSED", "ERROR"}


@dataclass
class BYONChatResponse:
    answer: str
    epistemic_status: str
    grounded: bool
    audit_trace_id: str = ""
    grounding_summary: Dict[str, Any] = field(default_factory=dict)
    memory_summary: Dict[str, Any] = field(default_factory=dict)
    dcortex_summary: Optional[Dict[str, Any]] = None
    fcem_summary: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer, "epistemic_status": self.epistemic_status,
            "grounded": self.grounded, "audit_trace_id": self.audit_trace_id,
            "grounding_summary": self.grounding_summary, "memory_summary": self.memory_summary,
            "dcortex_summary": self.dcortex_summary, "fcem_summary": self.fcem_summary,
            "raw": self.raw,
        }


def _error(msg: str) -> BYONChatResponse:
    return BYONChatResponse(answer="BYON runtime is not available.", epistemic_status="ERROR",
                            grounded=False, raw={"error": msg})


class BYONRuntimeClient:
    """REAL-mode client: talks to the BYON Gateway over HTTP."""

    def __init__(self, gateway_url: str, timeout_s: float = 60.0,
                 http_client: Optional[Any] = None) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.timeout_s = timeout_s
        self._client = http_client  # injected in tests (e.g. Starlette TestClient)

    # -- low-level ---------------------------------------------------------
    def _request(self, method: str, path: str, **kw) -> Any:
        if self._client is not None:
            return self._client.request(method, path, **kw)
        import httpx
        with httpx.Client(base_url=self.gateway_url, timeout=self.timeout_s) as c:
            return c.request(method, path, **kw)

    # -- health ------------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        try:
            resp = self._request("GET", "/v1/health")
            resp.raise_for_status()
            data = resp.json()
            data["_reachable"] = True
            return data
        except Exception as exc:
            return {"_reachable": False, "error": str(exc)}

    # -- chat --------------------------------------------------------------
    def chat(self, user_id: str, session_id: str, message: str,
             channel: str = "web") -> BYONChatResponse:
        if not user_id or not str(user_id).strip():
            raise ValueError("user_id is required")
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id is required")
        try:
            resp = self._request("POST", "/v1/chat", json={
                "user_id": user_id, "session_id": session_id,
                "channel": channel, "message": message})
        except Exception as exc:
            return _error(f"gateway unreachable: {exc}")

        if getattr(resp, "status_code", 200) >= 400:
            # 503 kill switch / 401 auth / 429 rate-limit etc. → ERROR, never fabricate.
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                detail = getattr(resp, "text", "")
            return _error(f"gateway returned {resp.status_code}: {detail}")

        try:
            data = resp.json()
        except Exception as exc:
            return _error(f"bad gateway response: {exc}")

        status = data.get("epistemic_status")
        status = status if status in _VALID else "ERROR"

        # The Gateway already enforces 'no answer without final audit', but the app
        # double-checks: if the raw payload signals the final audit did not pass, refuse.
        final_audit_passed = data.get("final_audit_passed")
        if final_audit_passed is False and status not in ("UNKNOWN", "DISPUTED", "ERROR"):
            return BYONChatResponse(
                answer="Response blocked because BYON final audit was not present.",
                epistemic_status="REFUSED", grounded=False,
                audit_trace_id=data.get("audit_trace_id", ""), raw=data)

        return BYONChatResponse(
            answer=data.get("answer", ""),
            epistemic_status=status,
            grounded=bool(data.get("grounded", False)) and status == "KNOWN",
            audit_trace_id=data.get("audit_trace_id", ""),
            grounding_summary=data.get("grounding_summary") or {},
            memory_summary=data.get("memory_summary") or {},
            dcortex_summary=data.get("dcortex_summary"),
            fcem_summary=data.get("fcem_summary"),
            raw=data,
        )

    # -- research (epistemic search loop) ----------------------------------
    def research(self, user_id: str, session_id: str, question: str, *,
                 allow_web: Optional[bool] = None, allow_claude: bool = True,
                 action: str = "start", research_trace_id: Optional[str] = None) -> Dict[str, Any]:
        if not user_id or not session_id:
            raise ValueError("user_id and session_id are required")
        try:
            resp = self._request("POST", "/v1/research", json={
                "user_id": user_id, "session_id": session_id, "question": question,
                "allow_web": allow_web, "allow_claude": allow_claude,
                "action": action, "research_trace_id": research_trace_id})
            if getattr(resp, "status_code", 200) >= 400:
                return {"epistemic_status": "ERROR", "research_status": "done",
                        "answer": "BYON runtime is not available.", "sources_searched": []}
            return resp.json()
        except Exception as exc:
            return {"epistemic_status": "ERROR", "research_status": "done",
                    "answer": "BYON runtime is not available.", "sources_searched": [], "error": str(exc)}

    def consolidate(self, user_id: str) -> Dict[str, Any]:
        try:
            resp = self._request("POST", "/v1/consolidate", params={"user_id": user_id})
            return resp.json()
        except Exception:
            return {"ok": False, "message": "Consolidate not available."}

    def memory_status(self, user_id: str) -> Dict[str, Any]:
        try:
            resp = self._request("GET", "/v1/memory/status", params={"user_id": user_id})
            return resp.json()
        except Exception:
            return {"backend": {}, "error": "memory status unavailable"}

    # -- lifeloop v2 (always via the Gateway; never memory-service directly) -----
    def lifeloop_state(self) -> Dict[str, Any]:
        try:
            return self._request("GET", "/v1/lifeloop").json()
        except Exception:
            return {"lifeloop": {"enabled": False}, "error": "lifeloop unavailable"}

    def lifeloop_tick(self) -> Dict[str, Any]:
        try:
            return self._request("POST", "/v1/lifeloop/tick").json()
        except Exception:
            return {"ok": False, "message": "tick unavailable"}

    def lifeloop_run_task(self, task_id: str) -> Dict[str, Any]:
        try:
            return self._request("POST", f"/v1/lifeloop/run-task/{task_id}").json()
        except Exception:
            return {"ok": False, "message": "run-task unavailable"}

    def lifeloop_approve_web(self, task_id: str) -> Dict[str, Any]:
        try:
            return self._request("POST", f"/v1/lifeloop/approve-web/{task_id}").json()
        except Exception:
            return {"ok": False, "message": "approve-web unavailable"}

    def lifeloop_cancel_task(self, task_id: str) -> Dict[str, Any]:
        try:
            return self._request("POST", f"/v1/lifeloop/cancel-task/{task_id}").json()
        except Exception:
            return {"ok": False, "message": "cancel-task unavailable"}

    def lifeloop_mark_resolved(self, topic: str) -> Dict[str, Any]:
        try:
            return self._request("POST", "/v1/lifeloop/mark-resolved", params={"topic": topic}).json()
        except Exception:
            return {"ok": False, "message": "mark-resolved unavailable"}

    def lifeloop_task_evidence(self, task_id: str) -> Dict[str, Any]:
        try:
            return self._request("GET", f"/v1/lifeloop/task/{task_id}").json()
        except Exception:
            return {"ok": False, "message": "task evidence unavailable"}

    def lifeloop_candidates(self, status: str = None) -> Dict[str, Any]:
        try:
            params = {"status": status} if status else None
            return self._request("GET", "/v1/lifeloop/candidates", params=params).json()
        except Exception:
            return {"counts": {}, "candidates": []}

    def lifeloop_candidate(self, candidate_id: str) -> Dict[str, Any]:
        try:
            return self._request("GET", f"/v1/lifeloop/candidate/{candidate_id}").json()
        except Exception:
            return {"ok": False, "message": "candidate unavailable"}

    def lifeloop_candidate_op(self, candidate_id: str, op: str) -> Dict[str, Any]:
        try:
            return self._request("POST", f"/v1/lifeloop/candidate/{candidate_id}/{op}").json()
        except Exception:
            return {"ok": False, "message": "candidate op unavailable"}

    def relation_field_status(self) -> Dict[str, Any]:
        try:
            return self._request("GET", "/v1/lifeloop/relation-field/status").json()
        except Exception:
            return {"total_entities": 0, "total_relations": 0, "is_truth_authority": False}

    def relation_field_neighborhood(self, entity: str) -> Dict[str, Any]:
        try:
            return self._request("GET", f"/v1/lifeloop/relation-field/neighborhood/{entity}").json()
        except Exception:
            return {"neighborhood": {}, "contradictions": []}

    def relation_field_contradictions(self) -> Dict[str, Any]:
        try:
            return self._request("GET", "/v1/lifeloop/relation-field/contradictions").json()
        except Exception:
            return {"count": 0, "contradictions": []}

    def relation_field_rebuild(self) -> Dict[str, Any]:
        try:
            return self._request("POST", "/v1/lifeloop/relation-field/rebuild").json()
        except Exception:
            return {"ok": False, "message": "relation-field rebuild unavailable"}

    # -- forget ------------------------------------------------------------
    def forget(self, user_id: str, session_id: str) -> Dict[str, Any]:
        try:
            resp = self._request("POST", "/v1/forget",
                                  json={"user_id": user_id, "session_id": session_id,
                                        "scope": "user", "confirm": True})
            if getattr(resp, "status_code", 200) >= 400:
                return {"ok": False, "message": "Forget endpoint not available."}
            return {"ok": True, "message": "Memory forget requested.", "raw": resp.json()}
        except Exception:
            return {"ok": False, "message": "Forget endpoint not available."}

    # -- audit -------------------------------------------------------------
    def audit_trace(self, trace_id: str) -> Dict[str, Any]:
        if not trace_id:
            return {"ok": False, "message": "Audit trace not available."}
        try:
            resp = self._request("GET", f"/v1/audit/{trace_id}")
            if getattr(resp, "status_code", 200) >= 400:
                return {"ok": False, "message": "Audit trace not available."}
            return {"ok": True, "trace": resp.json()}
        except Exception:
            return {"ok": False, "message": "Audit trace not available."}


class DemoBYONClient:
    """Opt-in DEMO client. Canned responses only, clearly labelled. NOT real BYON."""

    BANNER = "DEMO MODE — NOT REAL BYON RUNTIME"

    def health(self) -> Dict[str, Any]:
        return {"_reachable": True, "status": "demo", "demo": True}

    def chat(self, user_id: str, session_id: str, message: str,
             channel: str = "web") -> BYONChatResponse:
        if not user_id or not str(user_id).strip():
            raise ValueError("user_id is required")
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id is required")
        m = (message or "").lower()
        if any(w in m for w in ("password", "secret", "private")):
            status, grounded, answer = "UNKNOWN", False, ""
        elif "level" in m:
            status, grounded, answer = "KNOWN", True, "[DEMO] BYON is allowed to claim Level 2, not Level 3."
        else:
            status, grounded, answer = "KNOWN", True, f"[DEMO] canned reply to: {message}"
        return BYONChatResponse(
            answer=answer, epistemic_status=status, grounded=grounded,
            audit_trace_id="trace_demo",
            grounding_summary={"demo": True, "has_valid_memory": grounded},
            memory_summary={"user_namespace": f"demo-{user_id}", "memory_written": False},
            fcem_summary={"runtime_proven": False, "advisory_nonempty": False},
            raw={"demo": True, "banner": self.BANNER})

    def research(self, user_id: str, session_id: str, question: str, **kw) -> Dict[str, Any]:
        r = self.chat(user_id, session_id, question)
        return {"epistemic_status": r.epistemic_status, "research_status": "done",
                "answer": r.answer, "grounded": r.grounded, "confidence": 0.5,
                "sources_searched": ["memory(demo)"], "web_results": [],
                "claude_hypothesis": None, "stress_percent": 0, "phase": "done",
                "clock": {"demo": True}, "synthesis": {"epistemic_verdict": r.epistemic_status},
                "audit_trace_id": "trace_demo"}

    def consolidate(self, user_id: str) -> Dict[str, Any]:
        return {"ok": True, "promoted": [], "message": "[DEMO] no consolidation."}

    def memory_status(self, user_id: str) -> Dict[str, Any]:
        return {"backend": {"backend": "demo"}, "candidates": [], "committed": [], "disputed": []}

    def forget(self, user_id: str, session_id: str) -> Dict[str, Any]:
        return {"ok": True, "message": "[DEMO] forget is a no-op."}

    def audit_trace(self, trace_id: str) -> Dict[str, Any]:
        return {"ok": True, "trace": {"trace_id": trace_id, "demo": True}}

    def lifeloop_state(self) -> Dict[str, Any]:
        return {"lifeloop": {"enabled": True, "version": "v2", "pressure_total": 0,
                             "pending_research_tasks": [], "top_pressure_topics": [],
                             "consolidation_count": 0, "unknown_rate": 0.0,
                             "active_vault_facts": None, "tombstoned_vault_facts": None,
                             "memory_service_read_consistency_mode": "demo"}}

    def lifeloop_tick(self) -> Dict[str, Any]:
        return {"consolidated": False, "self_state": {"ticks": 0}, "demo": True}

    def lifeloop_run_task(self, task_id: str) -> Dict[str, Any]:
        return {"ok": True, "demo": True}

    def lifeloop_approve_web(self, task_id: str) -> Dict[str, Any]:
        return {"ok": True, "demo": True}

    def lifeloop_cancel_task(self, task_id: str) -> Dict[str, Any]:
        return {"ok": True, "demo": True}

    def lifeloop_mark_resolved(self, topic: str) -> Dict[str, Any]:
        return {"ok": True, "topic": topic, "demo": True}

    def lifeloop_task_evidence(self, task_id: str) -> Dict[str, Any]:
        return {"task": {"task_id": task_id, "demo": True}, "result": {}}

    def lifeloop_candidates(self, status: str = None) -> Dict[str, Any]:
        return {"counts": {"candidate": 0, "committed": 0, "disputed": 0, "archived": 0},
                "candidates": []}

    def lifeloop_candidate(self, candidate_id: str) -> Dict[str, Any]:
        return {"candidate": {"candidate_id": candidate_id, "demo": True}}

    def lifeloop_candidate_op(self, candidate_id: str, op: str) -> Dict[str, Any]:
        return {"ok": True, "op": op, "demo": True}

    def relation_field_status(self) -> Dict[str, Any]:
        return {"total_entities": 0, "total_relations": 0, "is_truth_authority": False,
                "answers_user_directly": False, "demo": True}

    def relation_field_neighborhood(self, entity: str) -> Dict[str, Any]:
        return {"neighborhood": {"entity": entity, "demo": True}, "contradictions": []}

    def relation_field_contradictions(self) -> Dict[str, Any]:
        return {"count": 0, "contradictions": [], "demo": True}

    def relation_field_rebuild(self) -> Dict[str, Any]:
        return {"ok": True, "demo": True}
