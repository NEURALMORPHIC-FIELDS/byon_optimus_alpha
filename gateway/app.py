"""BYON Gateway FastAPI application.

Exposes ONLY the controlled v1 surface — never the raw memory-service, D_Cortex,
FCE-M, FAISS, or internal auditor endpoints:

    POST /v1/chat
    POST /v1/feedback
    POST /v1/forget
    GET  /v1/memory/status
    GET  /v1/audit/{trace_id}
    GET  /v1/health
    GET  /v1/admin/metrics      (alpha admin — aggregate counters only)

Build the app with `create_app(...)`. Tests inject a deterministic BYON backend via
`app.dependency_overrides[get_backend]`; production uses the HTTP backend.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from . import __version__
from .audit import AuditLog, new_trace_id
from .auth import authenticate
from .byon_backend import BYONBackend, BYONResult, HttpBYONBackend
from .config import GatewayConfig
from .namespace import UserNamespace
from .normalizer import normalize
from .ratelimit import RateLimiter
from .types import (
    BYONChatRequest,
    BYONChatResponse,
    FeedbackRequest,
    ForgetRequest,
)


def get_backend() -> BYONBackend:  # overridden in tests / wired in create_app
    raise RuntimeError("backend not configured")


def _resolve_backend(cfg: GatewayConfig) -> BYONBackend:
    """Select the backend from env when none is injected.

    BYON_BACKEND_MODE=local (default) → self-contained real LocalBYONBackend (in-repo
    D_Cortex epistemic contract + real FCE-M advisory + optional Claude). This makes the
    Gateway runnable end-to-end with no external orchestrator.
    BYON_BACKEND_MODE=http (or BYON_BACKEND_URL set) → route to an external BYON orchestrator.
    """
    mode = os.environ.get("BYON_BACKEND_MODE", "").strip().lower()
    backend_url = os.environ.get("BYON_BACKEND_URL", "").strip()
    if mode == "http" or backend_url:
        return HttpBYONBackend(backend_url or cfg.orchestrator_url, cfg.backend_timeout_s)
    from .local_backend import LocalBYONBackend
    return LocalBYONBackend(fcem_root=os.environ.get("FCEM_MEMORY_ENGINE_ROOT") or None)


def create_app(config: Optional[GatewayConfig] = None,
               backend: Optional[BYONBackend] = None) -> FastAPI:
    cfg = config or GatewayConfig.from_env()
    audit = AuditLog(cfg.audit_root)
    limiter = RateLimiter(cfg.rate_limit_per_min)
    metrics: Dict[str, int] = {
        "messages": 0, "known": 0, "unknown": 0, "disputed": 0,
        "refused": 0, "error": 0, "feedback": 0, "forget": 0,
        "rate_limited": 0, "killed": 0,
    }
    resolved_backend = backend or _resolve_backend(cfg)

    app = FastAPI(title="BYON World Connector — Gateway", version=__version__)
    app.state.config = cfg
    app.state.audit = audit
    app.state.metrics = metrics

    def _backend() -> BYONBackend:
        return resolved_backend

    app.dependency_overrides.setdefault(get_backend, _backend)

    def _namespace(user_id: str) -> UserNamespace:
        ns = UserNamespace(cfg.users_root, user_id)
        if cfg.require_user_namespace:
            ns.ensure()
        return ns

    @app.get("/v1/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "service": "byon-gateway",
            "version": __version__,
            "alpha_mode": cfg.alpha_mode,
            "kill_switch": cfg.kill_switch,
            "require_final_audit": cfg.require_final_audit,
            "require_user_namespace": cfg.require_user_namespace,
            "allow_direct_memory_service": cfg.allow_direct_memory_service,
            "connectors": {
                "mcp": cfg.enable_mcp, "librechat": cfg.enable_librechat,
                "openclaw": cfg.enable_openclaw, "n8n": cfg.enable_n8n,
            },
            "backend": (resolved_backend.status()
                        if hasattr(resolved_backend, "status") else {"backend": "external"}),
            "full_level3_not_declared": True,
        }

    @app.post("/v1/chat", response_model=BYONChatResponse)
    def chat(req: BYONChatRequest, backend: BYONBackend = Depends(get_backend)) -> BYONChatResponse:
        if cfg.kill_switch:
            metrics["killed"] += 1
            raise HTTPException(status_code=503, detail="BYON_KILL_SWITCH active: external access disabled")

        auth = authenticate(req.user_id, req.auth_token)
        if not auth.authenticated:
            raise HTTPException(status_code=401, detail=f"unauthorized: {auth.reason}")

        if not limiter.allow(req.user_id):
            metrics["rate_limited"] += 1
            raise HTTPException(status_code=429, detail="rate limit exceeded")

        trace_id = new_trace_id()
        ns = _namespace(req.user_id)

        # The Gateway never answers; it asks BYON. On backend failure this is an
        # ERROR result with no answer — never a fabricated reply.
        try:
            result = backend.chat(user_id=req.user_id, session_id=req.session_id,
                                  channel=req.channel, message=req.message,
                                  namespace_dir=ns.root)
        except Exception as exc:  # defensive: a backend must not crash the gateway
            result = BYONResult(epistemic_status="ERROR", error=str(exc))

        response = normalize(result, audit_trace_id=trace_id,
                             user_namespace=ns.slug,
                             require_final_audit=cfg.require_final_audit)

        metrics["messages"] += 1
        metrics[response.epistemic_status.lower()] = metrics.get(response.epistemic_status.lower(), 0) + 1

        audit.write(trace_id, {
            "kind": "chat",
            "user_id": req.user_id, "user_slug": ns.slug, "session_id": req.session_id,
            "channel": req.channel, "message": req.message,
            "epistemic_status": response.epistemic_status,
            "grounded": response.grounded,
            "final_audit_passed": result.final_audit_passed,
            "backend_status": result.epistemic_status,
            "backend_error": result.error,
            "grounding_summary": response.grounding_summary.model_dump(),
            "memory_summary": response.memory_summary.model_dump(),
        }, user_namespace_dir=ns.root)
        return response

    @app.post("/v1/feedback")
    def feedback(req: FeedbackRequest) -> Dict[str, Any]:
        auth = authenticate(req.user_id, None)
        if not auth.authenticated and req.user_id == "":
            raise HTTPException(status_code=401, detail="missing user_id")
        ns = _namespace(req.user_id)
        trace_id = new_trace_id()
        rec = {"kind": "feedback", "user_id": req.user_id, "user_slug": ns.slug,
               "session_id": req.session_id, "rating": req.rating, "note": req.note,
               "about_trace": req.audit_trace_id}
        audit.write(trace_id, rec, user_namespace_dir=ns.root)
        try:
            fb = ns.path("feedback", f"{trace_id}.json")
            fb.write_text(__import__("json").dumps(rec, indent=2), encoding="utf-8")
        except OSError:
            pass
        metrics["feedback"] += 1
        return {"recorded": True, "audit_trace_id": trace_id}

    @app.post("/v1/forget")
    def forget(req: ForgetRequest, backend: BYONBackend = Depends(get_backend)) -> Dict[str, Any]:
        if not req.confirm:
            raise HTTPException(status_code=400, detail="forget requires confirm=true")
        ns = _namespace(req.user_id)
        out = backend.forget(user_id=req.user_id, namespace_dir=ns.root)
        trace_id = new_trace_id()
        audit.write(trace_id, {"kind": "forget", "user_id": req.user_id,
                               "user_slug": ns.slug, "backend": out},
                    user_namespace_dir=ns.root)
        metrics["forget"] += 1
        return {"forget_requested": True, "audit_trace_id": trace_id, "backend": out}

    @app.get("/v1/memory/status")
    def memory_status(user_id: str, backend: BYONBackend = Depends(get_backend)) -> Dict[str, Any]:
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=422, detail="user_id is required")
        ns = _namespace(user_id)
        out = backend.memory_status(user_id=user_id, namespace_dir=ns.root)
        return {"user_namespace": ns.slug, "subdirs": ns.subdirs(), "backend": out}

    @app.get("/v1/audit/{trace_id}")
    def audit_trace(trace_id: str) -> JSONResponse:
        rec = audit.read(trace_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="audit trace not found")
        return JSONResponse(rec)

    @app.get("/v1/admin/metrics")
    def admin_metrics() -> Dict[str, Any]:
        total = max(1, metrics["messages"])
        return {
            "counters": dict(metrics),
            "rates": {
                "unknown_rate": round(metrics["unknown"] / total, 4),
                "disputed_rate": round(metrics["disputed"] / total, 4),
                "refused_rate": round(metrics["refused"] / total, 4),
                "error_rate": round(metrics["error"] / total, 4),
            },
            "audit_records": audit.count(),
        }

    return app
