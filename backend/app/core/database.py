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

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, JSON, Boolean, ForeignKey, text
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
    conversation_transcript = Column(JSON, default=list)
    conversation_memory = Column(JSON, default=dict)

    # Analysis
    emergency_type = Column(String(50), default="")
    department_assigned = Column(String(50), default="UNASSIGNED")
    resolution_status = Column(String(20), default="PENDING")
    priority = Column(String(20), default="LOW")
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
    learning_feedback_type = Column(String(30), default="")

    # Cascade log (which models were used)
    cascade_log = Column(JSON, default=list)

    # PII stats
    pii_entities_count = Column(Integer, default=0)

    # Timestamps
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<CallRecord {self.call_id} state={self.state}>"


class MLTrainingData(Base):
    """Gold standard corrections for active learning."""
    __tablename__ = "ml_training_data"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(String(20), index=True)
    transcript = Column(Text, nullable=False)
    corrected_department = Column(String(50), nullable=False)
    source = Column(String(20), nullable=False) # 'LLM' or 'AGENT'
    applied = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
        await _ensure_call_record_columns(conn)

    logger.info("Database initialised: %s", settings.database_url)


async def _ensure_call_record_columns(conn) -> None:
    """Add demo-era columns to existing SQLite databases without data loss."""
    result = await conn.execute(text("PRAGMA table_info(call_records)"))
    existing = {row[1] for row in result.fetchall()}
    columns = {
        "conversation_transcript": "TEXT DEFAULT '[]'",
        "conversation_memory": "TEXT DEFAULT '{}'",
        "learning_feedback_type": "VARCHAR(30) DEFAULT ''",
    }
    for name, definition in columns.items():
        if name not in existing:
            await conn.execute(text(f"ALTER TABLE call_records ADD COLUMN {name} {definition}"))


def get_session() -> AsyncSession:
    """Get a new async database session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    return _session_factory()


# ── Repository Functions ────────────────────────────────────────────────────

async def save_call_record(session_data: dict[str, Any]) -> CallRecord:
    """Persist a completed call session to the database."""
    async with get_session() as db:
        from sqlalchemy import select
        call_id = session_data.get("call_id", "")
        stmt = select(CallRecord).where(CallRecord.call_id == call_id)
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            record = CallRecord(call_id=call_id)
            db.add(record)
        
        record.state = session_data.get("state", record.state)
        record.language_detected = session_data.get("language_detected", record.language_detected)
        record.raw_transcript = session_data.get("raw_transcript", record.raw_transcript)
        record.scrubbed_transcript = session_data.get("scrubbed_transcript", record.scrubbed_transcript)
        record.restated_summary = session_data.get("restated_summary", record.restated_summary)
        record.conversation_transcript = session_data.get("conversation_transcript", record.conversation_transcript)
        record.conversation_memory = session_data.get("conversation_memory", record.conversation_memory)
        record.emergency_type = session_data.get("emergency_type", record.emergency_type)
        record.department_assigned = session_data.get("department_assigned", record.department_assigned)
        record.resolution_status = session_data.get("resolution_status", record.resolution_status)
        record.priority = session_data.get("priority", record.priority)
        record.severity = session_data.get("severity", record.severity)
        record.sentiment = session_data.get("sentiment", record.sentiment)
        record.location_hint = session_data.get("location_hint", record.location_hint)
        record.cultural_context = session_data.get("cultural_context", record.cultural_context)
        record.key_details = session_data.get("key_details", record.key_details)
        record.confidence = session_data.get("confidence", record.confidence)
        record.distress_score = session_data.get("distress_score", record.distress_score)
        record.distress_level = session_data.get("distress_level", record.distress_level)
        if session_data.get("caller_confirmed") is not None:
            record.caller_confirmed = session_data.get("caller_confirmed")
        record.agent_edited = session_data.get("agent_edited", record.agent_edited)
        record.agent_corrections = session_data.get("agent_corrections", record.agent_corrections)
        record.learning_feedback_type = session_data.get("learning_feedback_type", record.learning_feedback_type)
        record.cascade_log = session_data.get("cascade_log", record.cascade_log)
        record.pii_entities_count = session_data.get("pii_entities_count", record.pii_entities_count)
        
        if not record.id:
            record.started_at = session_data.get("started_at", datetime.now(timezone.utc))
        record.completed_at = datetime.now(timezone.utc)

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
        record.learning_feedback_type = corrections.get("feedback_type", "agent_edit")
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
                "department_assigned": r.department_assigned,
                "resolution_status": r.resolution_status,
                "priority": r.priority,
                "severity": r.severity,
                "sentiment": r.sentiment,
                "raw_transcript": r.raw_transcript,
                "conversation_transcript": r.conversation_transcript,
                "conversation_memory": r.conversation_memory,
                "restated_summary": r.restated_summary,
                "location_hint": r.location_hint,
                "cultural_context": r.cultural_context,
                "key_details": r.key_details,
                "pii_entities_count": r.pii_entities_count,
                "confidence": r.confidence,
                "distress_score": r.distress_score,
                "caller_confirmed": r.caller_confirmed,
                "agent_edited": r.agent_edited,
                "agent_corrections": r.agent_corrections,
                "learning_feedback_type": r.learning_feedback_type,
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
                "conversation_memory": r.conversation_memory,
                "conversation_transcript": r.conversation_transcript,
                "learning_feedback_type": r.learning_feedback_type,
                "caller_confirmed": r.caller_confirmed,
            }
            for r in records
        ]

async def resolve_grievance(call_id: str) -> bool:
    async with get_session() as db:
        from sqlalchemy import select
        stmt = select(CallRecord).where(CallRecord.call_id == call_id)
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return False
        record.resolution_status = "RESOLVED"
        await db.commit()
        return True

async def get_analytics_overview() -> dict:
    async with get_session() as db:
        from sqlalchemy import select, func
        
        # total calls
        total_stmt = select(func.count(CallRecord.id))
        total_calls = (await db.execute(total_stmt)).scalar() or 0
        
        # resolved
        resolved_stmt = select(func.count(CallRecord.id)).where(CallRecord.resolution_status == "RESOLVED")
        resolved_calls = (await db.execute(resolved_stmt)).scalar() or 0
        
        # By department
        dept_stmt = select(CallRecord.department_assigned, func.count(CallRecord.id)).group_by(CallRecord.department_assigned)
        dept_result = await db.execute(dept_stmt)
        departments = [{"name": row[0], "count": row[1]} for row in dept_result.all()]
        
        # By status
        status_stmt = select(CallRecord.resolution_status, func.count(CallRecord.id)).group_by(CallRecord.resolution_status)
        status_result = await db.execute(status_stmt)
        statuses = [{"name": row[0], "count": row[1]} for row in status_result.all()]
        
        return {
            "total_calls": total_calls,
            "resolved_calls": resolved_calls,
            "resolution_rate": round(resolved_calls / total_calls * 100) if total_calls > 0 else 0,
            "departments": departments,
            "statuses": statuses
        }

async def save_ml_training_data(call_id: str, transcript: str, corrected_department: str, source: str) -> None:
    """Save a correction to be used for active learning."""
    async with get_session() as db:
        record = MLTrainingData(
            call_id=call_id,
            transcript=transcript,
            corrected_department=corrected_department,
            source=source
        )
        db.add(record)
        await db.commit()

async def get_unapplied_training_data() -> list[dict]:
    """Get all pending corrections that need to be applied to the model."""
    async with get_session() as db:
        from sqlalchemy import select
        stmt = select(MLTrainingData).where(MLTrainingData.applied == False)
        result = await db.execute(stmt)
        records = result.scalars().all()
        return [
            {
                "id": r.id,
                "transcript": r.transcript,
                "department": r.corrected_department
            }
            for r in records
        ]

async def mark_training_data_applied(ids: list[int]) -> None:
    """Mark training data as successfully applied to the model."""
    if not ids: return
    async with get_session() as db:
        from sqlalchemy import update
        stmt = update(MLTrainingData).where(MLTrainingData.id.in_(ids)).values(applied=True)
        await db.execute(stmt)
        await db.commit()
