"""
WebSocket Call Handler — Real-Time Audio + Control Channel
============================================================
Handles bidirectional WebSocket communication between the operator
dashboard and the verification engine.

Protocol (JSON frames):
    Client → Server:
        { "type": "audio",      "data": "<base64 PCM>" }
        { "type": "transcript",  "text": "..." }
        { "type": "confirm",     "confirmed": true/false }
        { "type": "start" }

    Server → Client:
        { "event": "state_change", "state": "...", ... }
        { "event": "audio_processed", "distress": {...} }
        { "event": "restatement", "restatement": "..." }
        { "event": "VERIFIED", ... }
        { "event": "SAFE_HUMAN_TAKEOVER", ... }
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from app.core.verification_fsm import VerificationEngine
from app.models import CallSession, VerificationState, WSEvent

logger = logging.getLogger("samvaad.ws_handler")


class ConnectionManager:
    """Manages active WebSocket connections for broadcasting dashboard updates."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}  # call_id → [ws]
        self._sessions: dict[str, CallSession] = {}
        self._engine = VerificationEngine()

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
            # Keep session in memory for review
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

            case _:
                await ws.send_json(
                    {"event": "error", "message": f"Unknown type: {msg_type}"}
                )

    async def _handle_audio(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Process incoming audio chunk."""
        audio_b64 = msg.get("data", "")
        if not audio_b64:
            return
        audio_bytes = base64.b64decode(audio_b64)
        event = await self._engine.process_audio(session, audio_bytes)
        await self._broadcast(call_id, event)

    async def _handle_transcript(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Process ASR transcript and run full verification pipeline."""
        text = msg.get("text", "").strip()
        if not text:
            return

        # LISTEN → SCRUB
        event = self._engine.receive_transcript(session, text)
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
            await self._broadcast(call_id, event)

    async def _handle_confirm(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Handle caller confirmation/rejection of restatement."""
        confirmed = msg.get("confirmed", False)
        event = self._engine.confirm(session, confirmed)
        await self._broadcast(call_id, event)

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
