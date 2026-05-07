"""
Samvaad 1092 — Domain Models
==============================
Pydantic v2 models shared across all subsystems. These are the canonical
"language" of the application — every WebSocket frame, every internal event,
and every dashboard payload is typed through these schemas.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ── Verification State Machine States ────────────────────────────────────────
class VerificationState(str, enum.Enum):
    """
    The 1092 Verification Loop lifecycle.

    Flow:
        INIT → LISTEN → SCRUB → ANALYZE → RESTATE →
        WAIT_FOR_CONFIRM → VERIFIED
                                ↓ (rejected / low confidence)
                        HUMAN_TAKEOVER
    """

    INIT = "INIT"
    LISTEN = "LISTEN"
    SCRUB = "SCRUB"
    ANALYZE = "ANALYZE"
    RESTATE = "RESTATE"
    WAIT_FOR_CONFIRM = "WAIT_FOR_CONFIRM"
    VERIFIED = "VERIFIED"
    HUMAN_TAKEOVER = "HUMAN_TAKEOVER"


# ── Distress Level ───────────────────────────────────────────────────────────
class DistressLevel(str, enum.Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"  # triggers SAFE_HUMAN_TAKEOVER


# ── Call Session ─────────────────────────────────────────────────────────────
class CallSession(BaseModel):
    """Root aggregate for one active 1092 call."""

    call_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    ticket_id: str = Field(default_factory=lambda: f"1092-{uuid.uuid4().hex[:6].upper()}")
    state: VerificationState = VerificationState.INIT
    preferred_language_code: str = "unknown"
    preferred_language_label: str = "auto"
    language_detected: str = "unknown"
    raw_transcript: str = ""
    latest_transcript: str = ""
    partial_transcript: str = ""
    scrubbed_transcript: str = ""
    latest_scrubbed_transcript: str = ""
    restated_summary: str = ""
    caller_confirmed: bool | None = None
    clarification_count: int = 0
    required_slot: str = "issue"
    call_slots: dict[str, Any] = Field(default_factory=dict)
    conversation_memory: dict[str, Any] = Field(default_factory=dict)
    conversation_transcript: list[dict[str, Any]] = Field(default_factory=list)
    optional_detail_count: int = 0
    latency_marks: dict[str, float] = Field(default_factory=dict)
    distress_score: float = 0.0
    distress_level: DistressLevel = DistressLevel.LOW
    sentiment: str = ""
    confidence: float = 0.0
    department_assigned: str = "UNASSIGNED"
    resolution_status: str = "PENDING"
    priority: str = "LOW"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pii_entities_found: list[PIIEntity] = Field(default_factory=list)
    analysis_result: AnalysisResult | None = None
    cascade_log: list[CascadeEntry] = Field(default_factory=list)

    model_config = {"use_enum_values": True}


# ── PII Entity ───────────────────────────────────────────────────────────────
class PIIEntity(BaseModel):
    """A single PII span detected during the SCRUB phase."""

    entity_type: str  # AADHAAR, PHONE, NAME, ADDRESS, etc.
    original: str
    replacement: str  # e.g. "[AADHAAR_REDACTED]"
    start: int
    end: int


# ── Analysis Result ──────────────────────────────────────────────────────────
class AnalysisResult(BaseModel):
    """Output of the LLM ANALYZE phase."""

    request_type: str | None = None
    emergency_type: str | None = None
    department: str | None = None
    line_department: str | None = None
    secondary_department: str | None = None
    location_hint: str | None = None
    severity: str | None = None
    priority: str | None = None
    sentiment: str | None = None
    language_detected: str | None = None
    key_details: list[str] = Field(default_factory=list)
    cultural_context: str | None = None
    semantic_distress_score: float = 0.0
    empathy_note: str | None = None
    priority_reason: str | None = None
    abuse_risk: str | None = None
    abuse_score: float = 0.0
    abuse_action: str | None = None
    abuse_reason: str | None = None
    status_lookup: str | None = None
    specialized_helpline: str | None = None
    emergency_referral: bool = False
    operator_hint: str | None = None
    needs_clarification: bool = False
    requires_immediate_takeover: bool = False
    confidence: float = 0.0


# ── Cascade Entry ────────────────────────────────────────────────────────────
class CascadeEntry(BaseModel):
    """Log entry for every LLM call in the cascade."""

    provider: str
    model: str
    purpose: str  # "sentiment" | "analysis" | "restatement"
    latency_ms: float
    success: bool
    error: str | None = None


# ── WebSocket Event Payloads ────────────────────────────────────────────────
class WSEvent(BaseModel):
    """Canonical WebSocket event frame sent to the dashboard."""

    event: str
    call_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = Field(default_factory=dict)


# Rebuild forward references
CallSession.model_rebuild()
