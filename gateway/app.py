# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""BYON Gateway FastAPI application.

Exposes ONLY the controlled v1 surface - never the raw memory-service, D_Cortex,
FCE-M, FAISS, or internal auditor endpoints:

    POST /v1/chat
    POST /v1/feedback
    POST /v1/forget
    GET  /v1/memory/status
    GET  /v1/audit/{trace_id}
    GET  /v1/health
    GET  /v1/admin/metrics      (alpha admin - aggregate counters only)

Build the app with `create_app(...)`. Tests inject a deterministic BYON backend via
`app.dependency_overrides[get_backend]`; production uses the HTTP backend.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from gateway import __version__
from gateway.audit import AuditLog, new_trace_id
from gateway.auth import authenticate
from gateway.byon_backend import BYONBackend, BYONResult, HttpBYONBackend
from gateway.config import GatewayConfig
from gateway.namespace import UserNamespace
from gateway.normalizer import normalize
from gateway.ratelimit import RateLimiter
from gateway.session_events import SessionEvents
from gateway.types import (
    BYONChatRequest,
    BYONChatResponse,
    FeedbackRequest,
    ForgetRequest,
    ResearchRequest,
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
    if mode == "memory_service":
        from gateway.memory_service_backend import MemoryServiceBackend
        return MemoryServiceBackend(cfg.memory_service_url)
    if mode == "http" or backend_url:
        return HttpBYONBackend(backend_url or cfg.orchestrator_url, cfg.backend_timeout_s)
    from gateway.local_backend import LocalBYONBackend
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

    # BYONLifeLoop v1 - internal circulation (no memory authority). Holds self_state and
    # triggers the canonical fce_consolidate; truth/storage stay in the memory-service.
    from gateway.lifeloop import BYONLifeLoop
    lifeloop = BYONLifeLoop()
    _mem = getattr(resolved_backend, "mem", None)

    # Cycle 7: autonomous memory-only task runner. Runs a task through the CANONICAL research loop
    # (web off, audit on), stores the result as a CANDIDATE (never committed truth) under the
    # existing ContinuousLearning policy. Never runs web/secret tasks.
    def _lifeloop_task_runner(task: Dict[str, Any]) -> Dict[str, Any]:
        b = resolved_backend
        if not hasattr(b, "research"):
            return {"epistemic_status": "ERROR", "error": "no research backend"}
        ns = _namespace("lifeloop")
        # Cycle 15 (TRACK D): pass acquisition_context (repo_root from BYON_REPO_ROOT) so the 13.3
        # project_files / corpus / external-LLM adapters actually fire for gap-repair tasks.
        from gateway.relation_maintenance import build_gap_acquisition_context
        out = b.research(user_id="lifeloop", session_id="lifeloop_auto", question=task["question"],
                         namespace_dir=ns.root, allow_web=False, allow_claude=True, action="start",
                         acquisition_context=build_gap_acquisition_context())
        syn = out.get("synthesis") or {}
        sources = syn.get("sources") or out.get("sources_searched") or []
        status = out.get("epistemic_status")
        candidate_id = None
        try:   # Cycle 8: ingest the result as a CANDIDATE (never committed here; only consolidation commits)
            from gateway.candidate_lifecycle import CandidateLifecycle
            lcyc = CandidateLifecycle(ns.root, b.mem if hasattr(b, "mem") else None, "lifeloop")
            cand = lcyc.ingest_task_result(
                task_id=task["task_id"], topic=task.get("topic", ""),
                claim=(out.get("answer") or "")[:300], sources_used=sources,
                epistemic_status=status, source_class=out.get("source_class"),
                source_event_ids=task.get("trigger_event_ids") or [],
                is_secret=(out.get("query_class") == "secret"))
            candidate_id = (cand or {}).get("candidate_id")
            if cand:    # Cycle 10: keep the relation field fresh without a full rebuild
                try:
                    from gateway.relation_field import lifeloop_field, RelationFieldBuilder
                    rfield = lifeloop_field(cfg.users_root)
                    RelationFieldBuilder(rfield, mem_client=b.mem if hasattr(b, "mem") else None,
                                         lifecycle=lcyc).incremental_update({"type": "candidate",
                                                                             "candidate": cand})
                except Exception:
                    pass
        except Exception:
            pass
        return {"epistemic_status": status, "answer_summary": (out.get("answer") or "")[:200],
                "sources_used": sources, "confidence": out.get("confidence"),
                "audit_trace_id": out.get("audit_trace_id"), "candidate_id": candidate_id,
                "stored_as": "disputed" if status == "DISPUTED" else "candidate"}
    lifeloop.set_task_runner(_lifeloop_task_runner)

    # Cycle 8: candidate consolidation (the only path that moves candidate state) + status, both
    # over the canonical memory-service. FCE-M state only sets attention/priority, never truth.
    def _candidate_consolidator() -> Any:
        from gateway.candidate_lifecycle import CandidateLifecycle
        ns = _namespace("lifeloop")
        lcyc = CandidateLifecycle(ns.root, getattr(resolved_backend, "mem", None), "lifeloop")
        fce = {"contested": (lifeloop.pressure.total() >= lifeloop.pressure_threshold)}
        return lcyc.consolidate(fce_state=fce)

    def _candidate_status_provider() -> Any:
        from gateway.candidate_lifecycle import CandidateLifecycle
        ns = _namespace("lifeloop")
        lcyc = CandidateLifecycle(ns.root, getattr(resolved_backend, "mem", None), "lifeloop")
        return {"counts": lcyc.counts(),
                "active": [{"candidate_id": c["candidate_id"], "claim": c["claim"][:80],
                            "status": c["status"], "evidence_count": c["evidence_count"],
                            "contradiction_count": c.get("contradiction_count", 0),
                            "source_class": c.get("source_class")} for c in lcyc.list()[:25]],
                "commit_evidence_threshold": lcyc.commit_evidence}
    lifeloop.set_candidate_hooks(consolidator=_candidate_consolidator,
                                 status_provider=_candidate_status_provider)

    app = FastAPI(title="BYON World Connector - Gateway", version=__version__)
    app.state.config = cfg
    app.state.audit = audit
    app.state.metrics = metrics
    app.state.lifeloop = lifeloop

    def _backend() -> BYONBackend:
        return resolved_backend

    app.dependency_overrides.setdefault(get_backend, _backend)

    # Optional background circulation daemon (opt-in; run_byon enables it in REAL mode).
    if os.environ.get("BYON_LIFELOOP_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on"):
        import threading
        def _life_daemon() -> None:
            interval = float(os.environ.get("BYON_LIFELOOP_TICK_SECONDS", "60"))
            while True:
                time.sleep(interval)
                try:
                    lifeloop.tick(_mem)
                except Exception:
                    pass
        threading.Thread(target=_life_daemon, daemon=True).start()

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
        # ERROR result with no answer - never a fabricated reply.
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
        lifeloop.record_interaction(question=req.message, status=response.epistemic_status,
                                    user_id=req.user_id, session_id=req.session_id,
                                    sources=response.grounding_summary.sources,
                                    audit_trace_id=trace_id, answer_head=response.answer)

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
        try:
            SessionEvents(ns.root, req.session_id).log_turn(
                question=req.message, answer=response.answer,
                epistemic_status=response.epistemic_status, intent=None,
                sources=response.grounding_summary.sources, audit_trace_id=trace_id)
        except Exception:
            pass
        return response

    @app.post("/v1/research")
    def research(req: ResearchRequest, backend: BYONBackend = Depends(get_backend)) -> Dict[str, Any]:
        if cfg.kill_switch:
            metrics["killed"] += 1
            raise HTTPException(status_code=503, detail="BYON_KILL_SWITCH active")
        auth = authenticate(req.user_id, None)
        if not auth.authenticated:
            raise HTTPException(status_code=401, detail=f"unauthorized: {auth.reason}")
        if not hasattr(backend, "research"):
            raise HTTPException(status_code=501, detail="active backend has no research loop (use memory_service backend)")
        ns = _namespace(req.user_id)
        trace_id = new_trace_id()
        try:
            out = backend.research(user_id=req.user_id, session_id=req.session_id,
                                   question=req.question, namespace_dir=ns.root,
                                   allow_web=req.allow_web, allow_claude=req.allow_claude,
                                   action=req.action, research_trace_id=req.research_trace_id)
        except Exception as exc:
            out = {"epistemic_status": "ERROR", "research_status": "done", "answer": "",
                   "error": str(exc), "sources_searched": [], "clock": {}, "stress_percent": 0}
        out["audit_trace_id"] = trace_id
        out["user_namespace"] = ns.slug
        st = str(out.get("epistemic_status", "ERROR"))
        metrics["messages"] += 1
        metrics[st.lower()] = metrics.get(st.lower(), 0) + 1
        _syn = out.get("synthesis") or {}
        lifeloop.record_interaction(question=req.question, status=st, user_id=req.user_id,
                                    session_id=req.session_id, query_class=out.get("query_class"),
                                    source_class=out.get("source_class"), intent=_syn.get("intent"),
                                    sources=_syn.get("sources"), audit_trace_id=trace_id,
                                    stress_percent=out.get("stress_percent"),
                                    answer_head=out.get("answer"))
        audit.write(trace_id, {"kind": "research", "user_id": req.user_id, "user_slug": ns.slug,
                               "session_id": req.session_id, "question": req.question,
                               "epistemic_status": st, "research_status": out.get("research_status"),
                               "sources_searched": out.get("sources_searched"),
                               "stress_percent": out.get("stress_percent"),
                               "research_trace_id": out.get("research_trace_id")},
                    user_namespace_dir=ns.root)
        try:
            SessionEvents(ns.root, req.session_id).log_turn(
                question=req.question, answer=out.get("answer", ""), epistemic_status=st,
                intent=(out.get("synthesis") or {}).get("intent"),
                sources=(out.get("synthesis") or {}).get("sources") or out.get("sources_searched"),
                audit_trace_id=trace_id)
        except Exception:
            pass
        return out

    @app.post("/v1/consolidate")
    def consolidate(user_id: str, backend: BYONBackend = Depends(get_backend)) -> Dict[str, Any]:
        if not user_id or not user_id.strip():
            raise HTTPException(status_code=422, detail="user_id is required")
        if not hasattr(backend, "consolidate"):
            return {"ok": False, "message": "active backend has no consolidation"}
        ns = _namespace(user_id)
        lifeloop.record_event("memory_action", topic="consolidate", user_id=user_id)
        return {"ok": True, **backend.consolidate(user_id=user_id, namespace_dir=ns.root)}

    @app.post("/v1/feedback")
    def feedback(req: FeedbackRequest, backend: BYONBackend = Depends(get_backend)) -> Dict[str, Any]:
        auth = authenticate(req.user_id, None)
        if not auth.authenticated and req.user_id == "":
            raise HTTPException(status_code=401, detail="missing user_id")
        ns = _namespace(req.user_id)
        trace_id = new_trace_id()
        # Feedback is a learning signal (Phase 9): reinforce / dispute / queue + FCE-M pressure.
        applied = {}
        if hasattr(backend, "apply_feedback"):
            try:
                applied = backend.apply_feedback(user_id=req.user_id, namespace_dir=ns.root,
                                                 rating=req.rating, value=req.value, note=req.note,
                                                 audit_trace_id=req.audit_trace_id)
            except Exception as exc:
                applied = {"ok": False, "error": str(exc)}
        rec = {"kind": "feedback", "user_id": req.user_id, "user_slug": ns.slug,
               "session_id": req.session_id, "rating": req.rating, "value": req.value,
               "note": req.note, "about_trace": req.audit_trace_id, "applied": applied}
        audit.write(trace_id, rec, user_namespace_dir=ns.root)
        try:
            fb = ns.path("feedback", f"{trace_id}.json")
            fb.write_text(__import__("json").dumps(rec, indent=2), encoding="utf-8")
        except OSError:
            pass
        metrics["feedback"] += 1
        lifeloop.record_feedback(rating=req.rating, user_id=req.user_id,
                                 question=req.value or req.note, audit_trace_id=req.audit_trace_id)
        try:
            SessionEvents(ns.root, req.session_id).append("feedback", rating=req.rating,
                                                          value=req.value, applied=applied)
        except Exception:
            pass
        return {"recorded": True, "audit_trace_id": trace_id, "applied": applied}

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

    @app.get("/v1/lifeloop")
    def lifeloop_state(backend: BYONBackend = Depends(get_backend)) -> Dict[str, Any]:
        return {"self_state": lifeloop.snapshot(),
                "lifeloop": lifeloop.status_v2(getattr(backend, "mem", None)),
                "consolidate_every": lifeloop.consolidate_every,
                "pressure_threshold": lifeloop.pressure_threshold}

    @app.post("/v1/lifeloop/tick")
    def lifeloop_tick(backend: BYONBackend = Depends(get_backend)) -> Dict[str, Any]:
        return lifeloop.tick(getattr(backend, "mem", None))

    @app.post("/v1/lifeloop/run-task/{task_id}")
    def lifeloop_run_task(task_id: str, backend: BYONBackend = Depends(get_backend)) -> Dict[str, Any]:
        from gateway.research_tasks import BLOCKED_NEEDS_PERMISSION, DONE, FAILED, RUNNING
        t = lifeloop.tasks.get(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="task not found")
        if t["status"] == BLOCKED_NEEDS_PERMISSION:
            return {"ok": False, "status": t["status"],
                    "message": "web research blocked - approve first via /v1/lifeloop/approve-web"}
        # internal (memory/vault/self_state) research runs through the canonical backend research
        # loop; it never bypasses memory-service/audit and never invents truth.
        lifeloop.tasks.set_status(task_id, RUNNING)
        try:
            if hasattr(backend, "research"):
                ns = _namespace(t.get("trigger_user", "lifeloop"))
                # Cycle 15 (TRACK D): thread acquisition_context (repo_root) so find_internal_evidence
                # / verify_with_project_source actually exercise the 13.3 project_files adapter.
                from gateway.relation_maintenance import build_gap_acquisition_context
                out = backend.research(user_id="lifeloop", session_id="lifeloop_task",
                                       question=t["question"], namespace_dir=ns.root,
                                       allow_web=("web" in t.get("allowed_sources", []) and
                                                  not t.get("requires_user_permission")),
                                       allow_claude=True, action="start",
                                       acquisition_context=build_gap_acquisition_context())
                res = {"epistemic_status": out.get("epistemic_status"),
                       "answer_head": (out.get("answer") or "")[:200],
                       "source_class": out.get("source_class")}
            else:
                res = {"epistemic_status": "ERROR", "answer_head": "no research backend"}
            lifeloop.tasks.set_status(task_id, DONE, result=res)
            lifeloop.ingest_event("research_task_done", task_id=task_id,
                                  epistemic_status=res.get("epistemic_status"))
            return {"ok": True, "task": lifeloop.tasks.get(task_id)}
        except Exception as exc:
            lifeloop.tasks.set_status(task_id, FAILED, result={"error": str(exc)})
            return {"ok": False, "error": str(exc)}

    @app.post("/v1/lifeloop/approve-web/{task_id}")
    def lifeloop_approve_web(task_id: str) -> Dict[str, Any]:
        t = lifeloop.tasks.approve_web(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="task not found")
        lifeloop.ingest_event("research_task_web_approved", task_id=task_id)
        return {"ok": True, "task": t}

    @app.post("/v1/lifeloop/cancel-task/{task_id}")
    def lifeloop_cancel_task(task_id: str) -> Dict[str, Any]:
        t = lifeloop.tasks.cancel(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="task not found")
        return {"ok": True, "task": t}

    @app.post("/v1/lifeloop/mark-resolved")
    def lifeloop_mark_resolved(topic: str) -> Dict[str, Any]:
        lifeloop.mark_resolved(topic)
        return {"ok": True, "topic": topic, "pressure_after": lifeloop.pressure.total()}

    @app.get("/v1/lifeloop/task/{task_id}")
    def lifeloop_task_evidence(task_id: str) -> Dict[str, Any]:
        t = lifeloop.tasks.get(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="task not found")
        return {"task": t, "result": (t.get("result") or {})}

    # -- Cycle 8: candidate lifecycle endpoints (over the canonical memory-service) ----
    def _candidate_lc() -> Any:
        from gateway.candidate_lifecycle import CandidateLifecycle
        ns = _namespace("lifeloop")
        return CandidateLifecycle(ns.root, getattr(resolved_backend, "mem", None), "lifeloop")

    @app.get("/v1/lifeloop/candidates")
    def lifeloop_candidates(status: Optional[str] = None) -> Dict[str, Any]:
        lc = _candidate_lc()
        return {"counts": lc.counts(), "candidates": lc.list(status)}

    @app.get("/v1/lifeloop/candidate/{candidate_id}")
    def lifeloop_candidate(candidate_id: str) -> Dict[str, Any]:
        c = _candidate_lc().get(candidate_id)
        if not c:
            raise HTTPException(status_code=404, detail="candidate not found")
        return {"candidate": c, "provenance": c.get("provenance")}

    @app.get("/v1/lifeloop/disputes")
    def lifeloop_disputes() -> Dict[str, Any]:
        """Cycle 9: why a candidate is disputed - relation, both sides, source classes, next step.
        Read-only explanation surface; LifeLoop still never answers the user or decides truth."""
        d = _candidate_lc().list_disputes()
        return {"count": len(d), "disputes": d}

    @app.post("/v1/lifeloop/consolidate-candidates")
    def lifeloop_consolidate_candidates() -> Dict[str, Any]:
        return {"ok": True, "decisions": _candidate_consolidator()}

    # -- Cycle 10: relational memory field (structure/navigation, NOT a truth store) ----
    def _relation_field(build_if_empty: bool=True) -> Any:
        from gateway.relation_field import lifeloop_field, RelationFieldBuilder
        from gateway.candidate_lifecycle import CandidateLifecycle
        field = lifeloop_field(cfg.users_root)
        if build_if_empty and field.is_empty():
            lc = CandidateLifecycle(field.dir, getattr(resolved_backend, "mem", None), "lifeloop")
            RelationFieldBuilder(field, mem_client=getattr(resolved_backend, "mem", None),
                                 lifecycle=lc).rebuild()
        return field

    @app.get("/v1/lifeloop/relation-field/status")
    def relation_field_status() -> Dict[str, Any]:
        return _relation_field().status()

    @app.get("/v1/lifeloop/relation-field/entity/{entity}")
    def relation_field_entity(entity: str) -> Dict[str, Any]:
        e = _relation_field().get_entity(entity)
        if e is None:
            raise HTTPException(status_code=404, detail="entity not found in relation field")
        return {"entity": e}

    @app.get("/v1/lifeloop/relation-field/neighborhood/{entity}")
    def relation_field_neighborhood(entity: str) -> Dict[str, Any]:
        from gateway import relation_reports as rr
        field = _relation_field()
        return {"neighborhood": rr.entity_neighborhood(field, entity),
                "contradictions": rr.contradiction_map(field, focus=entity)["contradictions"]}

    @app.get("/v1/lifeloop/relation-field/contradictions")
    def relation_field_contradictions() -> Dict[str, Any]:
        from gateway import relation_reports as rr
        field = _relation_field()
        return {"count": len(field.contradictions()),
                "contradictions": rr.contradiction_map(field)["contradictions"],
                "is_truth_authority": False}

    @app.post("/v1/lifeloop/relation-field/rebuild")
    def relation_field_rebuild(owner: Optional[str] = None) -> Dict[str, Any]:
        from gateway.relation_field import lifeloop_field, RelationFieldBuilder
        from gateway.candidate_lifecycle import CandidateLifecycle
        from gateway.vault_manifest import VaultManifest
        field = lifeloop_field(cfg.users_root)
        mem = getattr(resolved_backend, "mem", None)
        lc = CandidateLifecycle(field.dir, mem, "lifeloop")
        vm = None
        try:                                              # attach the active vault manifest if any
            vh = os.environ.get("BYON_VAULT_HASH")
            if vh:
                vm = VaultManifest(vh)
        except Exception:
            vm = None
        owners = [o for o in (owner, os.environ.get("BYON_VAULT_OWNER")) if o]
        stats = RelationFieldBuilder(field, mem_client=mem, lifecycle=lc, vault_manifest=vm,
                                     owners=owners).rebuild()
        return {"ok": True, "stats": stats, "status": field.status()}

    @app.post("/v1/lifeloop/relation-field/infer")
    def relation_field_infer(body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Grounded relation inference over a bounded text (operator/test surface). Adds CANDIDATE
        relations only - never commits; secret text yields nothing."""
        from gateway.relation_field import lifeloop_field, RelationFieldBuilder
        field = lifeloop_field(cfg.users_root)
        # explicit relation (operator surface): add one typed edge directly as a CANDIDATE
        if body.get("subject") and body.get("object"):
            rc = {"subject": body["subject"], "predicate": body.get("predicate", ""),
                  "object": body["object"], "relation_type": body.get("relation_type"),
                  "source_id": body.get("source", "operator:relation"),
                  "source_class": body.get("source_class"),
                  "is_contradiction": bool(body.get("is_contradiction")),
                  "evidence_quote": body.get("evidence_quote")}
            r = field.ingest_candidate_relation(rc)
            return {"ok": True, "candidates": [rc], "count": 1, "relation_id": r["relation_id"]}
        b = RelationFieldBuilder(field, mem_client=getattr(resolved_backend, "mem", None))
        cands = b.infer_text(body.get("text", ""), source=body.get("source", "operator:infer"),
                             source_class=body.get("source_class"), provenance=body.get("provenance"))
        return {"ok": True, "candidates": cands, "count": len(cands)}

    @app.post("/v1/lifeloop/relation-field/consolidate")
    def relation_field_consolidate() -> Dict[str, Any]:
        """The ONLY path that promotes inferred candidate relations (>=2 independent sources or a
        canonical/system source + quality + no contradiction). Never commits DISPUTED_OR_UNSAFE."""
        field = _relation_field(build_if_empty=False)
        decisions = field.consolidate()
        return {"ok": True, "decisions": decisions, "status": field.status()}

    @app.get("/v1/lifeloop/relation-field/path")
    def relation_field_path(source: str, target: Optional[str] = None, depth: int = 2,
                            include_inverse: bool = False) -> Dict[str, Any]:
        return _relation_field().multi_hop_path(source, target, max_depth=depth,
                                                include_inverse=include_inverse)

    @app.get("/v1/lifeloop/relation-field/explain-path")
    def relation_field_explain_path(source: str, target: Optional[str] = None, depth: int = 2,
                                    include_inverse: bool = False) -> Dict[str, Any]:
        from gateway import relation_reports as rr
        return rr.render_path_explanation(_relation_field(), source, target,
                                          include_inverse=include_inverse, max_depth=depth)

    @app.get("/v1/lifeloop/relation-field/contradiction-history")
    def relation_field_contradiction_history() -> Dict[str, Any]:
        field = _relation_field()
        return {"history": field.contradiction_history(),
                "unresolved": [c for c in field.contradiction_history()
                               if c.get("current_status") not in ("resolved", "superseded")]}

    @app.post("/v1/lifeloop/relation-field/scan-gaps")
    def relation_field_scan_gaps() -> Dict[str, Any]:
        """Cycle 13: turn weak/disputed/vault-only/decayed relation gaps into controlled internal
        research tasks (memory-only auto, web needs permission, secret-derived skipped)."""
        from gateway.relation_field import RelationGapScanner
        gaps = RelationGapScanner(_relation_field(build_if_empty=False), tasks=lifeloop.tasks).scan()
        return {"ok": True, "count": len(gaps), "gaps": gaps}

    @app.post("/v1/lifeloop/relation-field/resolve-contradiction/{contradiction_id}")
    def relation_field_resolve_contradiction(contradiction_id: str,
                                             body: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
        rec = _relation_field(build_if_empty=False).resolve_contradiction(
            contradiction_id, resolution_source=body.get("resolution_source", "operator"),
            status=body.get("status", "resolved"))
        if rec is None:
            raise HTTPException(status_code=404, detail="contradiction not found")
        return {"ok": True, "contradiction": rec}

    @app.post("/v1/lifeloop/relation-field/propose")
    def relation_field_propose() -> Dict[str, Any]:
        """The relation field PROPOSES candidates back to the candidate lifecycle (missing fact /
        contradiction / dependency / consolidation). It cannot commit and cannot override policy."""
        from gateway.relation_field import RelationProposer
        from gateway.candidate_lifecycle import CandidateLifecycle
        field = _relation_field()
        lc = CandidateLifecycle(field.dir, getattr(resolved_backend, "mem", None), "lifeloop")
        proposals = RelationProposer(field, lifecycle=lc).run()
        return {"ok": True, "count": len(proposals), "proposals": proposals}

    @app.post("/v1/lifeloop/candidate/{candidate_id}/{op}")
    def lifeloop_candidate_op(candidate_id: str, op: str) -> Dict[str, Any]:
        lc = _candidate_lc()
        if op == "mark-false":
            r = lc.mark_false(candidate_id)
        elif op == "mark-important":
            r = lc.mark_important(candidate_id)
        elif op == "request-evidence":
            r = lc.request_more_evidence(candidate_id)
        elif op == "approve-commit":
            r = lc.approve_commit(candidate_id)
            return {"ok": bool(r.get("ok")), **r}
        elif op == "archive":
            r = lc.archive(candidate_id)
        else:
            raise HTTPException(status_code=400, detail=f"unknown op {op}")
        if not r:
            raise HTTPException(status_code=404, detail="candidate not found")
        return {"ok": True, "candidate": r}

    @app.get("/v1/admin/metrics")
    def admin_metrics() -> Dict[str, Any]:
        total = max(1, metrics["messages"])
        return {
            "counters": dict(metrics),
            "lifeloop": lifeloop.snapshot(),
            "rates": {
                "unknown_rate": round(metrics["unknown"] / total, 4),
                "disputed_rate": round(metrics["disputed"] / total, 4),
                "refused_rate": round(metrics["refused"] / total, 4),
                "error_rate": round(metrics["error"] / total, 4),
            },
            "audit_records": audit.count(),
        }

    return app
