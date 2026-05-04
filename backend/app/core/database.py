"""
Samvaad 1092 — Database & Learning Signal Persistence
========================================================
Implements the "Learning from Feedback" requirement:
    - Every verified call becomes a learning signal
    - Agent edits are captured for continuous improvement
    - Historical calls are searchable

Uses async SQLAlchemy + aiosqlite for zero-friction local persistence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, JSON, Boolean
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger("samvaad.database")


# ── ORM Base ─────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Call Record Table ────────────────────────────────────────────────────────

class CallRecord(Base):
    """Persistent record of a completed (verified or escalated) call."""

    __tablename__ = "call_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(String(20), unique=True, nullable=False, index=True)
    state = Column(String(20), nullable=False)  # VERIFIED | HUMAN_TAKEOVER
    language_detected = Column(String(20), default="unknown")

    # Transcripts
    raw_transcript = Column(Text, default="")
    scrubbed_transcript = Column(Text, default="")
    restated_summary = Column(Text, default="")

    # Analysis
    emergency_type = Column(String(50), default="")
    severity = Column(String(20), default="")
    sentiment = Column(String(30), default="")
    location_hint = Column(Text, default="")
    cultural_context = Column(Text, default="")
    key_details = Column(JSON, default=list)

    # Scores
    confidence = Column(Float, default=0.0)
    distress_score = Column(Float, default=0.0)
    distress_level = Column(String(20), default="LOW")

    # Verification
    caller_confirmed = Column(Boolean, nullable=True)

    # Agent edits (learning signals)
    agent_edited = Column(Boolean, default=False)
    agent_corrections = Column(JSON, default=dict)  # {field: new_value}

    # Cascade log (which models were used)
    cascade_log = Column(JSON, default=list)

    # PII stats
    pii_entities_count = Column(Integer, default=0)

    # Timestamps
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<CallRecord {self.call_id} state={self.state}>"


# ── Engine & Session Factory ────────────────────────────────────────────────

_engine = None
_session_factory = None


async def init_db() -> None:
    """Initialise the database engine and create tables."""
    global _engine, _session_factory
    _engine = create_async_engine(settings.database_url, echo=False)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database initialised: %s", settings.database_url)


def get_session() -> AsyncSession:
    """Get a new async database session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    return _session_factory()


# ── Repository Functions ────────────────────────────────────────────────────

async def save_call_record(session_data: dict[str, Any]) -> CallRecord:
    """Persist a completed call session to the database."""
    record = CallRecord(
        call_id=session_data.get("call_id", ""),
        state=session_data.get("state", ""),
        language_detected=session_data.get("language_detected", "unknown"),
        raw_transcript=session_data.get("raw_transcript", ""),
        scrubbed_transcript=session_data.get("scrubbed_transcript", ""),
        restated_summary=session_data.get("restated_summary", ""),
        emergency_type=session_data.get("emergency_type", ""),
        severity=session_data.get("severity", ""),
        sentiment=session_data.get("sentiment", ""),
        location_hint=session_data.get("location_hint", ""),
        cultural_context=session_data.get("cultural_context", ""),
        key_details=session_data.get("key_details", []),
        confidence=session_data.get("confidence", 0.0),
        distress_score=session_data.get("distress_score", 0.0),
        distress_level=session_data.get("distress_level", "LOW"),
        caller_confirmed=session_data.get("caller_confirmed"),
        agent_edited=session_data.get("agent_edited", False),
        agent_corrections=session_data.get("agent_corrections", {}),
        cascade_log=session_data.get("cascade_log", []),
        pii_entities_count=session_data.get("pii_entities_count", 0),
        started_at=session_data.get("started_at", datetime.now(timezone.utc)),
        completed_at=datetime.now(timezone.utc),
    )

    async with get_session() as db:
        db.add(record)
        await db.commit()
        await db.refresh(record)

    logger.info("Saved call record: %s (state=%s)", record.call_id, record.state)
    return record


async def save_agent_edit(call_id: str, corrections: dict[str, Any]) -> bool:
    """Save agent corrections as learning signals."""
    async with get_session() as db:
        from sqlalchemy import select
        stmt = select(CallRecord).where(CallRecord.call_id == call_id)
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            logger.warning("Cannot save edits: call_id=%s not found", call_id)
            return False

        record.agent_edited = True
        record.agent_corrections = corrections
        await db.commit()
        logger.info("Saved agent edits for call_id=%s: %s", call_id, list(corrections.keys()))
        return True


async def get_call_history(limit: int = 50) -> list[dict]:
    """Retrieve recent call records for the dashboard."""
    async with get_session() as db:
        from sqlalchemy import select
        stmt = (
            select(CallRecord)
            .order_by(CallRecord.completed_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        records = result.scalars().all()

        return [
            {
                "call_id": r.call_id,
                "state": r.state,
                "language": r.language_detected,
                "emergency_type": r.emergency_type,
                "severity": r.severity,
                "sentiment": r.sentiment,
                "confidence": r.confidence,
                "distress_score": r.distress_score,
                "caller_confirmed": r.caller_confirmed,
                "agent_edited": r.agent_edited,
                "completed_at": r.completed_at.isoformat() if r.completed_at else "",
            }
            for r in records
        ]


async def get_learning_signals(limit: int = 100) -> list[dict]:
    """
    Retrieve verified call pairs (transcript ↔ verified intent) for training.
    These are calls where the caller confirmed OR the agent edited.
    """
    async with get_session() as db:
        from sqlalchemy import select, or_
        stmt = (
            select(CallRecord)
            .where(
                or_(
                    CallRecord.caller_confirmed == True,
                    CallRecord.agent_edited == True,
                )
            )
            .order_by(CallRecord.completed_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        records = result.scalars().all()

        return [
            {
                "call_id": r.call_id,
                "scrubbed_transcript": r.scrubbed_transcript,
                "restated_summary": r.restated_summary,
                "emergency_type": r.emergency_type,
                "severity": r.severity,
                "agent_corrections": r.agent_corrections,
                "caller_confirmed": r.caller_confirmed,
            }
            for r in records
        ]
