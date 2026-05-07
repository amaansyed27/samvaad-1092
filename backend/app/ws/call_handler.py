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
        { "type": "language_select", "language_code": "en-IN|kn-IN|hi-IN" }
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
import audioop
import io
import json
import logging
import time
import wave
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from app.core.sarvam_bridge import get_stt, get_tts
from app.core.verification_fsm import VerificationEngine
from app.models import CallSession, VerificationState, WSEvent
from app.core.ml_routing import predict_department

logger = logging.getLogger("samvaad.ws_handler")


class ConnectionManager:
    """Manages active WebSocket connections for broadcasting dashboard updates."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}  # call_id → [ws]
        self._dashboard_connections: set[WebSocket] = set()
        self._sessions: dict[str, CallSession] = {}
        self._engine = VerificationEngine()
        self._stt = get_stt()
        self._tts = get_tts()
        self._stt_streams: dict[str, object] = {}
        self._stt_receivers: dict[str, asyncio.Task] = {}
        self._stt_stream_disabled: set[str] = set()
        self._pcm_buffers: dict[str, bytearray] = {}
        self._tts_tasks: dict[str, asyncio.Task] = {}
        self._assistant_started_at: dict[str, float] = {}
        self._turn_started_at: dict[str, float] = {}
        self._last_partial_at: dict[str, float] = {}
        self._twilio_input_block_until: dict[str, float] = {}
        self._last_unclear_prompt_at: dict[str, float] = {}

    @property
    def active_sessions(self) -> dict[str, CallSession]:
        return dict(self._sessions)

    def is_assistant_speaking(self, call_id: str) -> bool:
        task = self._tts_tasks.get(call_id)
        return bool(task and not task.done())

    def has_twilio_connection(self, call_id: str) -> bool:
        return any(getattr(conn, "is_twilio", False) for conn in self._connections.get(call_id, []))

    def is_twilio_input_blocked(self, call_id: str) -> bool:
        return time.perf_counter() < self._twilio_input_block_until.get(call_id, 0.0)

    def twilio_input_block_remaining_ms(self, call_id: str) -> int:
        remaining = self._twilio_input_block_until.get(call_id, 0.0) - time.perf_counter()
        return max(0, int(remaining * 1000))

    def _hold_twilio_input(self, call_id: str, seconds: float) -> None:
        if not self.has_twilio_connection(call_id):
            return
        self._twilio_input_block_until[call_id] = max(
            self._twilio_input_block_until.get(call_id, 0.0),
            time.perf_counter() + max(0.0, seconds),
        )

    def _queue_twilio_audio_block(self, call_id: str, audio_seconds: float) -> None:
        if not self.has_twilio_connection(call_id):
            return
        now = time.perf_counter()
        base = max(self._twilio_input_block_until.get(call_id, 0.0), now)
        self._twilio_input_block_until[call_id] = base + max(0.0, audio_seconds)

    async def connect_dashboard(self, ws: WebSocket) -> None:
        """Register a global dashboard observer."""
        await ws.accept()
        self._dashboard_connections.add(ws)
        logger.info("Global Dashboard WS connected")

    async def disconnect_dashboard(self, ws: WebSocket) -> None:
        if ws in self._dashboard_connections:
            self._dashboard_connections.remove(ws)
        logger.info("Global Dashboard WS disconnected")

    async def connect(self, ws: WebSocket, call_id: str | None = None) -> CallSession:
        """Accept a new WebSocket and create/join a call session."""
        session = CallSession() if call_id is None else self._sessions.get(call_id)
        if session is None:
            session = CallSession(call_id=call_id) if call_id else CallSession()

        cid = session.call_id
        self._sessions[cid] = session
        self._connections.setdefault(cid, []).append(ws)

        # Transition to LISTEN
        event = self._engine.start_listening(session)
        await self._broadcast(cid, event)
        await self._broadcast(
            cid,
            {
                "event": "ivr_menu",
                "prompt": "Press 1 for English. ಕನ್ನಡಕ್ಕಾಗಿ 2 ಒತ್ತಿರಿ. हिंदी के लिए 3 दबाएँ.",
                "spoken_prompt": "Press 1 for English. Kannadadalli sevege eradu ottiri. Hindi ke liye teen dabaye.",
                "options": [
                    {"digit": "1", "language_code": "en-IN", "label": "English", "dialect": "English"},
                    {"digit": "2", "language_code": "kn-IN", "label": "Kannada", "dialect": "Kannada"},
                    {"digit": "3", "language_code": "hi-IN", "label": "Hindi", "dialect": "Hindi"},
                ],
            },
        )

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
            case "audio_frame":
                await self._handle_audio_frame(session, msg, call_id)

            case "audio_end":
                await self._handle_audio_end(session, msg, call_id)

            case "audio":
                await self._handle_audio(session, msg, call_id)

            case "transcript":
                await self._handle_transcript(session, msg, call_id)

            case "confirm":
                await self._handle_confirm(session, msg, call_id)

            case "language_select" | "dtmf":
                await self._handle_language_select(session, msg, call_id)

            case "start":
                event = self._engine.start_listening(session)
                await self._broadcast(call_id, event)

            case "takeover":
                await self._handle_takeover(session, msg, call_id)

            case "agent_edit" | "correction":
                await self._handle_agent_edit(session, msg, call_id)

            case _:
                await ws.send_json(
                    {"event": "error", "message": f"Unknown type: {msg_type}"}
                )

    async def _handle_audio_frame(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Stream raw 16-bit PCM frames into Sarvam STT."""
        if session.state in (VerificationState.VERIFIED.value, VerificationState.HUMAN_TAKEOVER.value):
            return

        audio_b64 = msg.get("data", "")
        if not audio_b64:
            return

        pcm_bytes = base64.b64decode(audio_b64)
        sample_rate = int(msg.get("sample_rate") or 16000)
        rms_raw = float(msg.get("rms") or (audioop.rms(pcm_bytes, 2) if pcm_bytes else 0.0))
        should_barge_in = bool(msg.get("barge_in", True))
        if msg.get("source") == "twilio":
            since_assistant_ms = (time.perf_counter() - self._assistant_started_at.get(call_id, 0.0)) * 1000
            if since_assistant_ms < 1200 and rms_raw < 180:
                should_barge_in = False

        if should_barge_in and call_id in self._tts_tasks and not self._tts_tasks[call_id].done():
            self._tts_tasks[call_id].cancel()
            await self._broadcast(call_id, {"event": "playback_cancel", "rms": rms_raw})

        self._pcm_buffers.setdefault(call_id, bytearray()).extend(pcm_bytes)
        self._turn_started_at.setdefault(call_id, time.perf_counter())

        now = time.perf_counter()
        if now - self._last_partial_at.get(call_id, 0.0) > 0.8:
            rms = audioop.rms(pcm_bytes, 2) / 32768 if pcm_bytes else 0.0
            await self._broadcast(
                call_id,
                {
                    "event": "audio_processed",
                    "distress": {
                        "score": min(rms * 12, 1.0),
                        "level": "MODERATE" if rms > 0.04 else "LOW",
                        "features": {"rms": min(rms * 12, 1.0)},
                    },
                },
            )
            self._last_partial_at[call_id] = now

        stream = self._stt_streams.get(call_id)
        if call_id in self._stt_stream_disabled:
            return
        if stream is None:
            try:
                stt_language = session.preferred_language_code or "en-IN"
                stream = await asyncio.wait_for(
                    self._stt.connect_stream(
                        language_code=stt_language,
                        sample_rate=sample_rate,
                    ),
                    timeout=0.35,
                )
                self._stt_streams[call_id] = stream
                self._stt_receivers[call_id] = asyncio.create_task(
                    self._receive_stt_stream(call_id, session)
                )
            except Exception as exc:
                logger.warning("Streaming STT unavailable, will use REST fallback: %s", exc)
                self._stt_stream_disabled.add(call_id)
                return

        try:
            await stream.send_pcm(pcm_bytes)
        except Exception as exc:
            logger.warning("Streaming STT send failed: %s", exc)

    async def _handle_audio_end(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Flush a streamed utterance; REST STT is used if no final arrives."""
        buffered_bytes = len(self._pcm_buffers.get(call_id, b""))
        await self._broadcast(call_id, {
            "event": "stt_status",
            "status": "audio_end_received",
            "buffered_bytes": buffered_bytes,
            "streaming_enabled": call_id not in self._stt_stream_disabled,
        })
        stream = self._stt_streams.get(call_id)
        if stream is not None:
            try:
                await stream.flush()
            except Exception as exc:
                logger.warning("Streaming STT flush failed: %s", exc)

        await asyncio.sleep(0.25)
        if session.partial_transcript:
            transcript = session.partial_transcript
            session.partial_transcript = ""
            await self._handle_final_transcript(
                session,
                transcript,
                call_id,
                language_code=session.preferred_language_code,
                language_prob=0.7,
            )
            self._pcm_buffers.pop(call_id, None)
            return

        pcm = bytes(self._pcm_buffers.pop(call_id, b""))
        if not pcm:
            await self._broadcast(call_id, {
                "event": "stt_status",
                "status": "empty_audio_buffer",
            })
            return
        if msg.get("source") == "twilio" and len(pcm) < 16000:
            await self._broadcast(call_id, {
                "event": "stt_status",
                "status": "short_twilio_buffer_ignored",
                "buffered_bytes": len(pcm),
            })
            return
        sample_rate = int(msg.get("sample_rate") or 16000)
        await self._broadcast(call_id, {
            "event": "stt_status",
            "status": "rest_fallback_started",
            "buffered_bytes": len(pcm),
            "sample_rate": sample_rate,
        })
        await self._handle_audio(
            session,
            {"data": base64.b64encode(_pcm16_to_wav(pcm, sample_rate)).decode("utf-8")},
            call_id,
        )

    async def _receive_stt_stream(self, call_id: str, session: CallSession) -> None:
        """Receive Sarvam streaming STT messages and fan out partial/final events."""
        stream = self._stt_streams.get(call_id)
        if stream is None:
            return
        try:
            while True:
                message = await stream.recv()
                transcript, is_final, language_code, language_prob = _parse_stt_stream_message(message)
                if not transcript:
                    continue
                if is_final:
                    session.partial_transcript = ""
                    await self._handle_final_transcript(
                        session,
                        transcript,
                        call_id,
                        language_code=language_code,
                        language_prob=language_prob,
                    )
                    self._pcm_buffers.pop(call_id, None)
                else:
                    session.partial_transcript = transcript
                    elapsed = _elapsed_ms(self._turn_started_at.get(call_id))
                    await self._broadcast(
                        call_id,
                        {
                            "event": "partial_transcript",
                            "transcript": transcript,
                            "language_code": language_code,
                            "language_prob": language_prob,
                            "latency_ms": elapsed,
                        },
                    )
                    if elapsed is not None:
                        session.latency_marks["stt_first_partial_ms"] = elapsed
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Streaming STT receiver stopped: %s", exc)
        finally:
            try:
                await stream.close()
            except Exception:
                pass
            self._stt_streams.pop(call_id, None)
            self._stt_receivers.pop(call_id, None)

    async def _handle_final_transcript(
        self,
        session: CallSession,
        transcript: str,
        call_id: str,
        *,
        language_code: str = "unknown",
        language_prob: float = 0.0,
    ) -> None:
        transcript = transcript.strip()
        if not transcript:
            return
        session.latency_marks["stt_final_ms"] = _elapsed_ms(self._turn_started_at.get(call_id)) or 0.0
        ml_route = predict_department(transcript)
        if _should_accept_ml_route(session, ml_route.get("department")):
            session.department_assigned = ml_route["department"]
        self._append_conversation_turn(session, "caller", transcript, language_code=language_code)
        await self._broadcast(call_id, {
            "event": "conversation_turn",
            "turn": session.conversation_transcript[-1],
            "conversation_memory": session.conversation_memory,
        })
        await self._broadcast(
            call_id,
            {
                "event": "final_transcript",
                "transcript": transcript,
                "language_code": language_code,
                "language_prob": language_prob,
                "ml_routing": ml_route,
            },
        )
        await self._broadcast(
            call_id,
            {
                "event": "transcript_received",
                "transcript": transcript,
                "language_code": language_code,
                "language_prob": language_prob,
                "ml_routing": ml_route,
            },
        )
        await self._run_pipeline(session, transcript, call_id)
        await self._persist_session(session)

    async def _handle_audio(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Process incoming audio: Acoustic Guardian → Sarvam STT → Pipeline."""
        # Check if the call is already resolved or escalated
        if session.state in (VerificationState.VERIFIED.value, VerificationState.HUMAN_TAKEOVER.value):
            return
            
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
        stt_language = session.preferred_language_code or "unknown"
        try:
            stt_result = await asyncio.wait_for(
                self._stt.transcribe(
                    audio_bytes,
                    language_code=stt_language,
                ),
                timeout=2.2,
            )
        except asyncio.TimeoutError:
            logger.warning("REST STT timed out for call_id=%s", call_id)
            await self._broadcast(call_id, {
                "event": "stt_status",
                "status": "rest_timeout",
            })
            await self._prompt_unclear_audio(call_id, session)
            return
        transcript = stt_result.get("transcript", "").strip()
        prob = stt_result.get("language_prob", 0.0)

        if not transcript:
            await self._broadcast(call_id, {
                "event": "stt_status",
                "status": "empty_transcript",
                "language_code": stt_result.get("language_code", "unknown"),
                "language_prob": prob,
            })
            await self._prompt_unclear_audio(call_id, session)
            return
        await self._broadcast(call_id, {
            "event": "stt_status",
            "status": "transcript_ready",
            "chars": len(transcript),
            "language_code": stt_result.get("language_code", "unknown"),
            "language_prob": prob,
        })

        # ── Hallucination & Noise Filtering ────────────────────────────────
        
        # 1. Known STT hallucination artifacts on silence/noise
        lower_t = transcript.lower()
        known_hallucinations = ["j j.", "okay, fine.", "hello.", "hello", "test.", "test", "yes.", "no."]
        if lower_t in known_hallucinations and prob < 0.75:
            logger.info("Filtered STT hallucination: '%s' (prob: %.3f)", transcript, prob)
            return

        # 2. Filter extremely short, low-confidence blips
        words = transcript.split()
        if len(words) < 3 and prob < 0.5:
            logger.info("Filtered low-prob short transcript: '%s' (prob: %.3f)", transcript, prob)
            return

        # 3. Filter repetitive loop hallucinations (e.g., "Yes, yes, yes, yes...")
        if len(words) > 3 and len(set(words)) == 1:
            logger.info("Filtered repetitive loop hallucination: '%s'", transcript)
            return

        # ───────────────────────────────────────────────────────────────────

        # Step 3: Run full verification pipeline with transcribed text
        await self._handle_final_transcript(
            session,
            transcript,
            call_id,
            language_code=stt_result.get("language_code", "unknown"),
            language_prob=prob,
        )

    async def _handle_transcript(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Process text transcript (simulator mode) and run full pipeline."""
        # Check if the call is already resolved or escalated
        if session.state in (VerificationState.VERIFIED.value, VerificationState.HUMAN_TAKEOVER.value):
            return
            
        text = msg.get("text", "").strip()
        if not text:
            return
            
        # Run Fast ML Routing
        ml_route = predict_department(text)
        if _should_accept_ml_route(session, ml_route.get("department")):
            session.department_assigned = ml_route["department"]
        await self._broadcast(call_id, {
            "event": "ml_routing_update",
            "ml_routing": ml_route
        })
            
        await self._broadcast(call_id, {
            "event": "final_transcript",
            "transcript": text,
            "language_code": session.preferred_language_code or "unknown",
            "language_prob": 1.0,
            "ml_routing": ml_route,
        })
        self._append_conversation_turn(session, "caller", text, language_code=session.preferred_language_code or "unknown")
        await self._broadcast(call_id, {
            "event": "conversation_turn",
            "turn": session.conversation_transcript[-1],
            "conversation_memory": session.conversation_memory,
        })
        await self._run_pipeline(session, text, call_id)

    async def _handle_language_select(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Set the caller language from IVR digits or the dashboard demo."""
        language_code = msg.get("language_code")
        digit = str(msg.get("digit", "")).strip()
        if not language_code:
            language_code = {"1": "en-IN", "2": "kn-IN", "3": "hi-IN"}.get(digit, "unknown")

        event = self._engine.set_language(session, language_code)
        await self._broadcast(call_id, event)
        if not any(getattr(conn, "is_twilio", False) for conn in self._connections.get(call_id, [])):
            await self._stream_assistant_text(call_id, session, _language_lock_prompt(session))

    async def _run_pipeline(
        self, session: CallSession, transcript: str, call_id: str
    ) -> None:
        """Run the full SCRUB → ANALYZE → RESTATE pipeline."""
        # LISTEN → SCRUB
        event = await self._engine.receive_transcript(session, transcript)
        await self._broadcast(call_id, event)

        if session.state != VerificationState.SCRUB.value:
            if event.get("event") == "VERIFIED":
                await self._stream_assistant_text(call_id, session, event.get("dispatch_message", ""))
                await self._persist_session(session)
            return

        # SCRUB (PII redaction)
        event = self._engine.scrub(session)
        await self._broadcast(call_id, event)

        # ANALYZE (LLM cascade)
        event = await self._engine.analyse(session)
        await self._broadcast(call_id, event)
        if event.get("analysis"):
            await self._broadcast(call_id, {
                "event": "classification_update",
                "analysis": event["analysis"],
                "department": event["analysis"].get("department"),
                "emergency_type": event["analysis"].get("emergency_type"),
                "priority": event["analysis"].get("priority"),
                "severity": event["analysis"].get("severity"),
                "priority_reason": event["analysis"].get("priority_reason"),
                "empathy_note": event["analysis"].get("empathy_note"),
                "confidence": event.get("confidence"),
            })
            if event["analysis"].get("abuse_action") and event["analysis"].get("abuse_action") != "ALLOW":
                await self._broadcast(call_id, {
                    "event": "abuse_guardrail",
                    "risk": event["analysis"].get("abuse_risk"),
                    "score": event["analysis"].get("abuse_score"),
                    "action": event["analysis"].get("abuse_action"),
                    "reason": event["analysis"].get("abuse_reason"),
                })
            await self._broadcast(call_id, {
                "event": "conversation_memory_update",
                "conversation_memory": session.conversation_memory,
                "slots": session.call_slots,
            })
        if event.get("slots"):
            await self._broadcast(call_id, {"event": "slot_update", "slots": event["slots"]})
        if event.get("sentiment"):
            await self._broadcast(call_id, {
                "event": "sentiment_update",
                "sentiment": event["sentiment"],
                "confidence": event.get("confidence"),
            })
        session.latency_marks["analysis_ms"] = _elapsed_ms(self._turn_started_at.get(call_id)) or 0.0

        if session.state == VerificationState.HUMAN_TAKEOVER.value:
            return

        # If we're still on track (not taken over), generate restatement
        if session.state == VerificationState.RESTATE.value:
            event = await self._engine.restate(session)
            await self._broadcast(call_id, event)
            if event.get("needs_clarification"):
                await self._broadcast(call_id, {
                    "event": "clarification_required",
                    "prompt": session.restated_summary,
                    "slots": event.get("slots", {}),
                })
            if event.get("slots"):
                await self._broadcast(call_id, {"event": "slot_update", "slots": event["slots"]})
            if session.restated_summary:
                await self._stream_assistant_text(call_id, session, session.restated_summary)

    async def _handle_confirm(
        self, session: CallSession, msg: dict, call_id: str
    ) -> None:
        """Handle caller confirmation/rejection of restatement."""
        confirmed = msg.get("confirmed", False)
        event = await self._engine.confirm(session, confirmed)
        await self._broadcast(call_id, event)
        if event.get("slots"):
            await self._broadcast(call_id, {"event": "slot_update", "slots": event["slots"]})
        if confirmed and event.get("dispatch_message"):
            await self._stream_assistant_text(call_id, session, event["dispatch_message"])


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
        feedback_type = msg.get("feedback_type") or corrections.get("feedback_type")
        if feedback_type:
            corrections = {**corrections, "feedback_type": feedback_type}

        try:
            from app.core.database import save_agent_edit, save_ml_training_data
            await save_agent_edit(session.call_id, corrections)
            
            # If the agent corrected the department, add it to Active Learning
            if "department" in corrections and corrections["department"] != "UNKNOWN":
                await save_ml_training_data(
                    session.call_id,
                    session.raw_transcript,
                    corrections["department"],
                    "AGENT"
                )
                
            await self._broadcast(call_id, {
                "event": "agent_edit_saved",
                "corrections": corrections,
            })
            logger.info("Agent edit saved: call_id=%s fields=%s", call_id, list(corrections.keys()))
        except Exception as exc:
            logger.error("Failed to save agent edit: %s", exc)

    async def _stream_assistant_text(
        self,
        call_id: str,
        session: CallSession,
        text: str,
    ) -> None:
        """Broadcast assistant text and stream Sarvam TTS chunks to the browser."""
        if not text:
            return

        await self._broadcast(call_id, {"event": "assistant_text", "text": text})
        self._assistant_started_at[call_id] = time.perf_counter()
        self._hold_twilio_input(call_id, 0.9)
        self._append_conversation_turn(session, "assistant", text, language_code=_tts_language(session))
        await self._broadcast(call_id, {
            "event": "conversation_turn",
            "turn": session.conversation_transcript[-1],
            "conversation_memory": session.conversation_memory,
        })

        existing = self._tts_tasks.get(call_id)
        if existing and not existing.done():
            existing.cancel()
            await self._broadcast(call_id, {"event": "playback_cancel"})

        async def run() -> None:
            tts_start = time.perf_counter()
            first_audio_sent = False
            lang = _tts_language(session)
            try:
                async for chunk in self._tts.stream_synthesise(
                    text,
                    target_language=lang,
                ):
                    if not chunk.get("audio_base64"):
                        continue
                    self._queue_twilio_audio_block(
                        call_id,
                        _estimate_audio_seconds(
                            chunk["audio_base64"],
                            chunk.get("codec", "wav"),
                            int(chunk.get("sample_rate") or 24000),
                        ),
                    )
                    if not first_audio_sent:
                        first_audio_ms = (time.perf_counter() - tts_start) * 1000
                        session.latency_marks["tts_first_audio_ms"] = first_audio_ms
                        first_audio_sent = True
                    await self._broadcast(call_id, {
                        "event": "assistant_audio_chunk",
                        "audio": chunk["audio_base64"],
                        "codec": chunk.get("codec", "wav"),
                        "sample_rate": chunk.get("sample_rate", 24000),
                        "content_type": chunk.get("content_type", "audio/wav"),
                    })

                total_gap = _elapsed_ms(self._turn_started_at.pop(call_id, None))
                metrics = {
                    **session.latency_marks,
                    "total_turn_gap_ms": total_gap,
                }
                await self._broadcast(call_id, {"event": "latency_metrics", "metrics": metrics})
                if first_audio_sent:
                    self._hold_twilio_input(call_id, 0.65)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Assistant TTS stream failed: %s", exc)

        self._tts_tasks[call_id] = asyncio.create_task(run())

    async def _prompt_unclear_audio(self, call_id: str, session: CallSession) -> None:
        """Fast recovery when STT hears audio but cannot produce text."""
        if session.state in (VerificationState.VERIFIED.value, VerificationState.HUMAN_TAKEOVER.value):
            return
        now = time.perf_counter()
        if now - self._last_unclear_prompt_at.get(call_id, 0.0) < 4.0:
            await self._broadcast(call_id, {
                "event": "stt_status",
                "status": "unclear_prompt_suppressed",
            })
            return
        self._last_unclear_prompt_at[call_id] = now
        prompt = _unclear_audio_prompt(session)
        await self._broadcast(call_id, {
            "event": "clarification_required",
            "prompt": prompt,
            "reason": "stt_empty_or_timeout",
        })
        await self._stream_assistant_text(call_id, session, prompt)

    async def _persist_session(self, session: CallSession) -> None:
        """Persist a completed session to the database."""
        try:
            from app.core.database import save_call_record

            analysis = session.analysis_result
            data = {
                "call_id": session.call_id,
                "ticket_id": session.ticket_id,
                "state": session.state,
                "preferred_language_code": session.preferred_language_code,
                "language_detected": session.language_detected,
                "raw_transcript": session.raw_transcript,
                "scrubbed_transcript": session.scrubbed_transcript,
                "restated_summary": session.restated_summary,
                "emergency_type": analysis.emergency_type if analysis else "",
                "department_assigned": session.department_assigned,
                "resolution_status": session.resolution_status,
                "priority": session.priority,
                "severity": analysis.severity if analysis else "",
                "sentiment": session.sentiment,
                "location_hint": analysis.location_hint if analysis else "",
                "cultural_context": analysis.cultural_context if analysis else "",
                "key_details": analysis.key_details if analysis else [],
                "confidence": session.confidence,
                "distress_score": session.distress_score,
                "distress_level": session.distress_level,
                "caller_confirmed": session.caller_confirmed,
                "conversation_memory": session.conversation_memory,
                "conversation_transcript": session.conversation_transcript,
                "cascade_log": [e.model_dump() for e in session.cascade_log],
                "pii_entities_count": len(session.pii_entities_found),
                "started_at": session.started_at,
            }
            await save_call_record(data)
        except Exception as exc:
            logger.error("Failed to persist session %s: %s", session.call_id, exc)

    def _append_conversation_turn(
        self,
        session: CallSession,
        role: str,
        text: str,
        *,
        language_code: str = "unknown",
    ) -> None:
        """Keep a durable call-centre style turn log for the inbox and learning loop."""
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return
        turn = {
            "role": role,
            "text": cleaned,
            "language_code": language_code,
            "state": session.state,
            "required_slot": session.required_slot,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if not session.conversation_transcript or session.conversation_transcript[-1].get("text") != cleaned:
            session.conversation_transcript.append(turn)

    async def _broadcast(self, call_id: str, data: dict) -> None:
        """Send an event to all WebSocket connections for a call, plus global dashboards."""
        data["call_id"] = call_id
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        
        # 1. Send to specific call connections (including Twilio)
        conns = self._connections.get(call_id, [])
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                if getattr(ws, "is_twilio", False):
                    # Twilio requires a specific media format and doesn't care about state events.
                    # Only send TTS audio.
                    twilio_payload = _audio_event_to_twilio_mulaw(data)
                    if twilio_payload:
                        tw_msg = {
                            "event": "media",
                            "streamSid": ws.stream_sid,
                            "media": {"payload": twilio_payload}
                        }
                        await ws.send_json(tw_msg)
                else:
                    await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.remove(ws)

        # 2. Send to all global dashboard observers
        dead_dashboards: list[WebSocket] = []
        for dws in self._dashboard_connections:
            try:
                await dws.send_json(data)
            except Exception:
                dead_dashboards.append(dws)
        for dws in dead_dashboards:
            self._dashboard_connections.remove(dws)


def _pcm16_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_bytes)
    return buffer.getvalue()


def _parse_stt_stream_message(message: dict) -> tuple[str, bool, str, float]:
    data = message.get("data") if isinstance(message.get("data"), dict) else {}
    transcript = (
        message.get("transcript")
        or message.get("text")
        or data.get("transcript")
        or data.get("text")
        or data.get("partial_transcript")
        or ""
    )
    is_final = bool(
        message.get("is_final")
        or message.get("final")
        or data.get("is_final")
        or data.get("final")
        or data.get("event_type") in {"final", "end"}
        or message.get("type") in {"final_transcript", "final"}
    )
    language_code = message.get("language_code") or data.get("language_code") or "unknown"
    language_prob = float(message.get("language_prob") or data.get("language_probability") or data.get("language_prob") or 0.0)
    return transcript.strip(), is_final, language_code, language_prob


def _audio_event_to_twilio_mulaw(data: dict) -> str:
    audio_b64 = data.get("tts_audio") or data.get("audio")
    if not audio_b64:
        return ""

    raw = base64.b64decode(audio_b64)
    codec = data.get("codec") or ("wav" if data.get("tts_audio") else "pcm")
    sample_rate = int(data.get("sample_rate") or 16000)

    if codec == "wav" or raw[:4] == b"RIFF":
        with wave.open(io.BytesIO(raw), "rb") as wav:
            sample_rate = wav.getframerate()
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            pcm = wav.readframes(wav.getnframes())
        if width != 2:
            pcm = audioop.lin2lin(pcm, width, 2)
        if channels > 1:
            pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
    elif codec == "mulaw":
        return audio_b64
    else:
        pcm = raw

    if sample_rate != 8000:
        pcm, _ = audioop.ratecv(pcm, 2, 1, sample_rate, 8000, None)
    mulaw = audioop.lin2ulaw(pcm, 2)
    return base64.b64encode(mulaw).decode("utf-8")


def _estimate_audio_seconds(audio_b64: str, codec: str, sample_rate: int) -> float:
    try:
        raw = base64.b64decode(audio_b64)
        if codec == "wav" or raw[:4] == b"RIFF":
            with wave.open(io.BytesIO(raw), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate() or sample_rate
            return frames / rate if rate else 0.0
        if codec == "mulaw":
            return len(raw) / float(sample_rate or 8000)
        return len(raw) / float(2 * (sample_rate or 24000))
    except Exception:
        return 0.0


def _tts_language(session: CallSession) -> str:
    if session.preferred_language_code and session.preferred_language_code != "unknown":
        return session.preferred_language_code
    return {
        "kannada": "kn-IN",
        "hindi": "hi-IN",
        "english": "en-IN",
        "mixed": "hi-IN",
    }.get((session.language_detected or "").lower(), "en-IN")


def _unclear_audio_prompt(session: CallSession) -> str:
    language = (session.preferred_language_label or session.language_detected or "english").lower()
    if language == "hindi":
        return "लाइन साफ नहीं है. कृपया अपनी शिकायत और अपना क्षेत्र या नजदीकी लैंडमार्क फिर से बताएं."
    if language == "kannada":
        return "ಲೈನ್ ಸ್ಪಷ್ಟವಾಗಿಲ್ಲ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ದೂರು ಮತ್ತು ಪ್ರದೇಶ ಅಥವಾ ಹತ್ತಿರದ ಗುರುತನ್ನು ಮತ್ತೊಮ್ಮೆ ಹೇಳಿ."
    return "The line is not clear. Please repeat your grievance once, including your area or nearest landmark."


def _language_lock_prompt(session: CallSession) -> str:
    language = (session.preferred_language_label or "english").lower()
    if language == "hindi":
        return "हिंदी चुनी गई है. कृपया अपनी शिकायत बताइए."
    if language == "kannada":
        return "ಕನ್ನಡ ಆಯ್ಕೆ ಮಾಡಲಾಗಿದೆ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ದೂರು ಹೇಳಿ."
    return "English selected. Please tell me your grievance."


def _should_accept_ml_route(session: CallSession, department: str | None) -> bool:
    if not department or department in {"UNKNOWN", "OTHER"}:
        return False
    current = session.department_assigned
    return current in {"UNASSIGNED", "UNKNOWN", "OTHER", ""}


def _elapsed_ms(start: float | None) -> float | None:
    if start is None:
        return None
    return round((time.perf_counter() - start) * 1000, 1)


# Singleton
_manager: ConnectionManager | None = None


def get_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager
