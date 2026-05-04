"""
WebSocket Call Handler — Real-Time Voice-to-Voice + Control Channel
====================================================================
Handles bidirectional WebSocket communication between the operator
dashboard and the verification engine.

Protocol (JSON frames):
    Client → Server:
        { "type": "audio",      "data": "<base64 PCM>" }
        { "type": "transcript",  "text": "..." }
        { "type": "confirm",     "confirmed": true/false }
        { "type": "start" }
        { "type": "takeover" }                              ← Manual takeover
        { "type": "agent_edit",  "corrections": {...} }     ← Agent edits

    Server → Client:
        { "event": "state_change", "state": "...", ... }
        { "event": "audio_processed", "distress": {...} }
        { "event": "transcript_received", "transcript": "...", ... }
        { "event": "restatement", "restatement": "...", "audio": "..." }
        { "event": "VERIFIED", ... }
        { "event": "SAFE_HUMAN_TAKEOVER", ... }
        { "event": "agent_edit_saved", ... }
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from app.core.sarvam_bridge import get_stt, get_tts
from app.core.verification_fsm import VerificationEngine
from app.models import CallSession, VerificationState, WSEvent

logger = logging.getLogger("samvaad.ws_handler")


class ConnectionManager:
    """Manages active WebSocket connections for broadcasting dashboard updates."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}  # call_id → [ws]
        self._sessions: dict[str, CallSession] = {}
        self._engine = VerificationEngine()
        self._stt = get_stt()
        self._tts = get_tts()

    @property
    def active_sessions(self) -> dict[str, CallSession]:
        return dict(self._sessions)

    async def connect(self, ws: WebSocket, call_id: str | None = None) -> CallSession:
        """Accept a new WebSocket and create/join a call session."""
        await ws.accept()

        session = CallSession() if call_id is None else self._sessions.get(call_id)
        if session is None:
            session = CallSession(call_id=call_id) if call_id else CallSession()

        cid = session.call_id
        self._sessions[cid] = session
        self._connections.setdefault(cid, []).append(ws)

        # Transition to LISTEN
        event = self._engine.start_listening(session)
        await self._broadcast(cid, event)

        logger.info("WS connected: call_id=%s", cid)
        return session

    async def disconnect(self, ws: WebSocket, call_id: str) -> None:
        """Remove a WebSocket from the connection pool."""
        conns = self._connections.get(call_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._connections.pop(call_id, None)

            # Persist completed sessions to database
            session = self._sessions.get(call_id)
            if session and session.state in (
                VerificationState.VERIFIED.value,
                VerificationState.HUMAN_TAKEOVER.value,
            ):
                await self._persist_session(session)

        logger.info("WS disconnected: call_id=%s", call_id)

    async def handle_message(
        self, ws: WebSocket, session: CallSession, raw: str
    ) -> None:
        """Route an incoming WebSocket message to the appropriate handler."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_json({"event": "error", "message": "Invalid JSON"})
            return

        msg_type = msg.get("type", "")
        call_id = session.call_id

        match msg_type:
            case "audio":
                await self._handle_audio(session, msg, call_id)

            case "transcript":
                await self._handle_transcript(session, msg, call_id)

            case "confirm":
                await self._handle_confirm(session, msg, call_id)

            case "start":
                event = self._engine.start_listening(session)
                await self._broadcast(call_id, event)

            case "takeover":
                await self._handle_takeover(session, msg, call_id)

            case "agent_edit":
                await self._handle_agent_edit(session, msg, call_id)

            case _:
                await ws.send_json(
                    {"event": "error", "message": f"Unknown type: {msg_type}"}
                )

    async def _handle_audio(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Process incoming audio: Acoustic Guardian → Sarvam STT → Pipeline."""
        audio_b64 = msg.get("data", "")
        if not audio_b64:
            return
        audio_bytes = base64.b64decode(audio_b64)

        # Step 1: Acoustic Guardian (on-device, parallel)
        distress_event = await self._engine.process_audio(session, audio_bytes)
        await self._broadcast(call_id, distress_event)

        # If takeover was triggered by acoustic distress, stop here
        if distress_event.get("event") == "SAFE_HUMAN_TAKEOVER":
            return

        # Step 2: Sarvam STT — transcribe audio
        stt_result = await self._stt.transcribe(audio_bytes)
        transcript = stt_result.get("transcript", "").strip()

        if not transcript:
            return

        # Send real-time transcript to dashboard
        await self._broadcast(call_id, {
            "event": "transcript_received",
            "transcript": transcript,
            "language_code": stt_result.get("language_code", "unknown"),
            "language_prob": stt_result.get("language_prob", 0.0),
        })

        # Step 3: Run full verification pipeline with transcribed text
        await self._run_pipeline(session, transcript, call_id)

    async def _handle_transcript(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Process text transcript (simulator mode) and run full pipeline."""
        text = msg.get("text", "").strip()
        if not text:
            return
        await self._run_pipeline(session, text, call_id)

    async def _run_pipeline(
        self, session: CallSession, transcript: str, call_id: str
    ) -> None:
        """Run the full SCRUB → ANALYZE → RESTATE pipeline."""
        # LISTEN → SCRUB
        event = self._engine.receive_transcript(session, transcript)
        await self._broadcast(call_id, event)

        # SCRUB (PII redaction)
        event = self._engine.scrub(session)
        await self._broadcast(call_id, event)

        # ANALYZE (LLM cascade)
        event = await self._engine.analyse(session)
        await self._broadcast(call_id, event)

        # If we're still on track (not taken over), generate restatement
        if session.state == VerificationState.RESTATE.value:
            event = await self._engine.restate(session)

            # TTS: Convert restatement to speech
            if session.restated_summary:
                # Detect language for TTS
                lang_map = {
                    "kannada": "kn-IN",
                    "hindi": "hi-IN",
                    "english": "en-IN",
                    "mixed": "hi-IN",  # default mixed to Hindi
                }
                tts_lang = lang_map.get(
                    session.language_detected.lower(), "en-IN"
                )
                tts_result = await self._tts.synthesise(
                    session.restated_summary,
                    target_language=tts_lang,
                )
                event["tts_audio"] = tts_result.get("audio_base64", "")

            await self._broadcast(call_id, event)

    async def _handle_confirm(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Handle caller confirmation/rejection of restatement."""
        confirmed = msg.get("confirmed", False)
        event = self._engine.confirm(session, confirmed)
        await self._broadcast(call_id, event)

        # Persist on terminal states
        if session.state in (
            VerificationState.VERIFIED.value,
            VerificationState.HUMAN_TAKEOVER.value,
        ):
            await self._persist_session(session)

    async def _handle_takeover(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Manual takeover triggered by the agent."""
        reason = msg.get("reason", "Agent initiated manual takeover")
        event = self._engine.force_takeover(session, reason)
        await self._broadcast(call_id, event)
        await self._persist_session(session)

    async def _handle_agent_edit(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Agent edits AI interpretation — captured as learning signal."""
        corrections = msg.get("corrections", {})
        if not corrections:
            return

        try:
            from app.core.database import save_agent_edit
            await save_agent_edit(session.call_id, corrections)
            await self._broadcast(call_id, {
                "event": "agent_edit_saved",
                "corrections": corrections,
            })
            logger.info("Agent edit saved: call_id=%s fields=%s", call_id, list(corrections.keys()))
        except Exception as exc:
            logger.error("Failed to save agent edit: %s", exc)

    async def _persist_session(self, session: CallSession) -> None:
        """Persist a completed session to the database."""
        try:
            from app.core.database import save_call_record

            analysis = session.analysis_result
            data = {
                "call_id": session.call_id,
                "state": session.state,
                "language_detected": session.language_detected,
                "raw_transcript": session.raw_transcript,
                "scrubbed_transcript": session.scrubbed_transcript,
                "restated_summary": session.restated_summary,
                "emergency_type": analysis.emergency_type if analysis else "",
                "severity": analysis.severity if analysis else "",
                "sentiment": session.sentiment,
                "location_hint": analysis.location_hint if analysis else "",
                "cultural_context": analysis.cultural_context if analysis else "",
                "key_details": analysis.key_details if analysis else [],
                "confidence": session.confidence,
                "distress_score": session.distress_score,
                "distress_level": session.distress_level,
                "caller_confirmed": session.caller_confirmed,
                "cascade_log": [e.model_dump() for e in session.cascade_log],
                "pii_entities_count": len(session.pii_entities_found),
                "started_at": session.started_at,
            }
            await save_call_record(data)
        except Exception as exc:
            logger.error("Failed to persist session %s: %s", session.call_id, exc)

    async def _broadcast(self, call_id: str, data: dict) -> None:
        """Send an event to all WebSocket connections for a call."""
        data["call_id"] = call_id
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        conns = self._connections.get(call_id, [])
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.remove(ws)


# Singleton
_manager: ConnectionManager | None = None


def get_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager
