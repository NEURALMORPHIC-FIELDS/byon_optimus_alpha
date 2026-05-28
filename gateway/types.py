# Copyright (c) 2024-2026 Vasile Lucian Borbeleac / FRAGMERGENT TECHNOLOGY S.R.L.
# Licensed under Apache-2.0.
"""Public request/response contract for the BYON Gateway.

The response ALWAYS carries an `epistemic_status` and an `audit_trace_id` - these
are non-optional by construction, so a caller can never receive an answer that is
not labelled with BYON's epistemic verdict and traceable to an audit record.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

Channel = Literal["web", "openclaw", "telegram", "whatsapp", "slack", "api"]
EpistemicStatus = Literal[
    "KNOWN", "PROVISIONAL", "PROVISIONAL_UNVERIFIED", "DISPUTED",
    "NEEDS_MORE_TIME", "ASK_USER_FOR_SOURCE", "BUDGET_REQUIRED", "UNKNOWN", "REFUSED", "ERROR",
    "SELF_STATE_GROUNDED", "ACTION_DONE", "ACTION_REQUIRED",
]


class ClientMetadata(BaseModel):
    display_name: Optional[str] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None


class BYONChatRequest(BaseModel):
    user_id: str
    session_id: str
    channel: Channel = "api"
    message: str
    auth_token: Optional[str] = None
    client_metadata: Optional[ClientMetadata] = None

    @field_validator("user_id", "session_id", "message")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must be a non-empty string")
        return str(v).strip()


class GroundingSummary(BaseModel):
    has_valid_memory: bool = False
    sources: List[str] = Field(default_factory=list)
    provenance_required: bool = True


class MemorySummary(BaseModel):
    user_namespace: str
    memory_written: bool = False
    memory_keys: Optional[List[str]] = None


class DCortexSummary(BaseModel):
    verdict: Optional[str] = None
    unknown_gate: Optional[bool] = None
    contradiction_status: Optional[str] = None


class FCEMSummary(BaseModel):
    runtime_proven: bool = False
    advisory_nonempty: bool = False
    pressure_max: Optional[float] = None


class BYONChatResponse(BaseModel):
    answer: str
    epistemic_status: EpistemicStatus
    grounded: bool
    audit_trace_id: str
    grounding_summary: GroundingSummary
    memory_summary: MemorySummary
    dcortex_summary: Optional[DCortexSummary] = None
    fcem_summary: Optional[FCEMSummary] = None


class FeedbackRequest(BaseModel):
    user_id: str
    session_id: str
    audit_trace_id: Optional[str] = None
    rating: Literal["correct", "right", "wrong", "false", "partially_correct",
                    "verify_again", "remember_this", "do_not_remember", "important",
                    "unsafe"] = "wrong"
    value: Optional[str] = None   # the fact/answer the feedback is about (optional)
    note: Optional[str] = None

    @field_validator("user_id", "session_id")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must be a non-empty string")
        return str(v).strip()


class ForgetRequest(BaseModel):
    user_id: str
    confirm: bool = False

    @field_validator("user_id")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must be a non-empty string")
        return str(v).strip()


class ResearchRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    allow_web: Optional[bool] = None
    allow_claude: bool = True
    research_trace_id: Optional[str] = None
    action: Literal["start", "continue", "conclude"] = "start"

    @field_validator("user_id", "session_id", "question")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("must be a non-empty string")
        return str(v).strip()
