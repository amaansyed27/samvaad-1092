"""
Twilio WebSocket Handler
========================
Handles real-time PSTN phone calls from Twilio Media Streams.
Decodes 8kHz µ-law audio to 16kHz PCM for Sarvam STT.
Encodes 16kHz PCM TTS responses back to 8kHz µ-law.
"""

from __future__ import annotations

import audioop
import base64
import json
import logging
import time
from fastapi import WebSocket, WebSocketDisconnect

from app.ws.call_handler import get_manager

logger = logging.getLogger("samvaad.twilio_handler")


TWILIO_SPEECH_START_RMS = 180
TWILIO_SPEECH_CONTINUE_RMS = 75
TWILIO_SPEECH_START_CHUNKS = 5
TWILIO_BARGE_IN_RMS = 1800
TWILIO_BARGE_IN_CHUNKS = 6
TWILIO_SILENCE_END_CHUNKS = 45
TWILIO_MAX_SPEECH_CHUNKS = 260
TWILIO_PREROLL_FRAMES = 8


def _twilio_vad_decision(
    *,
    rms: int,
    speech_active: bool,
    candidate_chunks: int,
    input_blocked: bool,
    blocked_chunks: int,
) -> tuple[bool, int, int, bool]:
    """Return speech decision, candidate count, blocked count, and barge-in flag."""
    if input_blocked:
        if rms >= TWILIO_BARGE_IN_RMS:
            blocked_chunks += 1
        else:
            blocked_chunks = max(0, blocked_chunks - 1)
        barge_in = blocked_chunks >= TWILIO_BARGE_IN_CHUNKS
        return barge_in, candidate_chunks if barge_in else 0, blocked_chunks, barge_in

    blocked_chunks = 0
    if speech_active:
        return rms > TWILIO_SPEECH_CONTINUE_RMS, candidate_chunks, blocked_chunks, False

    if rms > TWILIO_SPEECH_START_RMS:
        candidate_chunks += 1
    else:
        candidate_chunks = max(0, candidate_chunks - 1)
    return candidate_chunks >= TWILIO_SPEECH_START_CHUNKS, candidate_chunks, blocked_chunks, False


class TwilioMediaStreamHandler:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.stream_sid: str | None = None
        self.call_id: str | None = None
        self.manager = get_manager()
        self.session = None
        self._speech_active = False
        self._silence_chunks = 0
        self._speech_chunks = 0
        self._candidate_chunks = 0
        self._blocked_speech_chunks = 0
        self._ratecv_state = None
        self._pre_roll_frames: list[bytes] = []
        self._last_blocked_notice_at = 0.0

    async def handle(self) -> None:
        await self.ws.accept()
        logger.info("Twilio WebSocket connection established.")

        try:
            while True:
                message = await self.ws.receive_text()
                data = json.loads(message)
                event = data.get("event")

                if event == "start":
                    self.stream_sid = data["start"]["streamSid"]
                    # We can use Twilio's CallSid as our internal call_id
                    self.call_id = data["start"]["callSid"]
                    logger.info(f"Twilio Call Started: StreamSid={self.stream_sid}, CallSid={self.call_id}")
                    
                    # Mark WebSocket for the ConnectionManager to know it's Twilio
                    self.ws.is_twilio = True
                    self.ws.stream_sid = self.stream_sid

                    # Connect to our internal verification engine
                    self.session = await self.manager.connect(self.ws, call_id=self.call_id)
                    
                    # Extract Twilio location data from the custom parameters
                    custom_params = data.get("start", {}).get("customParameters", {})
                    language_code = custom_params.get("preferred_language_code", "unknown")
                    if language_code != "unknown":
                        await self.manager.handle_message(
                            self.ws,
                            self.session,
                            json.dumps({"type": "language_select", "language_code": language_code}),
                        )

                    location_data = {
                        "city": data.get("start", {}).get("fromCity") or custom_params.get("FromCity"),
                        "state": data.get("start", {}).get("fromState") or custom_params.get("FromState"),
                        "country": data.get("start", {}).get("fromCountry") or custom_params.get("FromCountry"),
                        "zip": data.get("start", {}).get("fromZip") or custom_params.get("FromZip"),
                        "caller_number": data.get("start", {}).get("from") or "Anonymous"
                    }
                    
                    if any(location_data.values()):
                        await self.manager._broadcast(self.call_id, {
                            "event": "location_update",
                            "location": location_data
                        })
                        logger.info(f"Twilio Location captured: {location_data}")

                    # Say a greeting

                    await self.send_tts("Welcome to the 1092 Emergency Helpline. Please state your emergency.")
                    
                elif event == "media":
                    if not self.session:
                        continue
                        
                    payload = data["media"]["payload"]
                    # 1. Decode base64
                    mulaw_bytes = base64.b64decode(payload)
                    
                    # 2. Convert 8kHz µ-law to 8kHz 16-bit PCM
                    pcm_8k = audioop.ulaw2lin(mulaw_bytes, 2)
                    
                    # 3. Resample 8kHz PCM to 16kHz PCM (for Sarvam/Librosa)
                    pcm_16k, self._ratecv_state = audioop.ratecv(
                        pcm_8k,
                        2,
                        1,
                        8000,
                        16000,
                        self._ratecv_state,
                    )

                    # Calculate RMS energy for VAD (Silence Gating)
                    rms = audioop.rms(pcm_16k, 2)
                    self._pre_roll_frames.append(pcm_16k)
                    self._pre_roll_frames = self._pre_roll_frames[-TWILIO_PREROLL_FRAMES:]
                    input_blocked = bool(
                        self.call_id
                        and (
                            self.manager.is_twilio_input_blocked(self.call_id)
                            or self.manager.is_assistant_speaking(self.call_id)
                        )
                    )
                    is_speech, self._candidate_chunks, self._blocked_speech_chunks, barge_in = _twilio_vad_decision(
                        rms=rms,
                        speech_active=self._speech_active,
                        candidate_chunks=self._candidate_chunks,
                        input_blocked=input_blocked,
                        blocked_chunks=self._blocked_speech_chunks,
                    )

                    if input_blocked and not barge_in:
                        now = time.perf_counter()
                        if now - self._last_blocked_notice_at > 1.0:
                            self._last_blocked_notice_at = now
                            await self.manager._broadcast(self.call_id, {
                                "event": "audio_activity",
                                "source": "twilio",
                                "status": "assistant_playout_blocked",
                                "rms": rms,
                                "remaining_ms": self.manager.twilio_input_block_remaining_ms(self.call_id),
                            })
                        continue

                    if is_speech and not self._speech_active:
                        await self.manager._broadcast(self.call_id, {
                            "event": "audio_activity",
                            "source": "twilio",
                            "status": "barge_in_started" if barge_in else "speech_started",
                            "rms": rms,
                        })
                        for frame in self._pre_roll_frames[:-1]:
                            await self.manager.handle_message(
                                self.ws,
                                self.session,
                                json.dumps({
                                    "type": "audio_frame",
                                    "data": base64.b64encode(frame).decode("utf-8"),
                                    "sample_rate": 16000,
                                    "source": "twilio",
                                    "barge_in": barge_in,
                                }),
                            )

                    if is_speech or self._speech_active:
                        msg = {
                            "type": "audio_frame",
                            "data": base64.b64encode(pcm_16k).decode("utf-8"),
                            "sample_rate": 16000,
                            "source": "twilio",
                            "rms": rms,
                            "barge_in": barge_in,
                        }
                        await self.manager.handle_message(self.ws, self.session, json.dumps(msg))

                    if is_speech:
                        self._speech_active = True
                        self._silence_chunks = 0
                        self._speech_chunks += 1

                        # Demo latency guard: don't wait for a long natural pause on PSTN.
                        if self._speech_chunks >= TWILIO_MAX_SPEECH_CHUNKS:
                            await self.manager.handle_message(
                                self.ws,
                                self.session,
                                json.dumps({"type": "audio_end", "sample_rate": 16000, "source": "twilio"}),
                            )
                            await self.manager._broadcast(self.call_id, {
                                "event": "audio_activity",
                                "source": "twilio",
                                "status": "speech_ended_max_window",
                                "rms": rms,
                            })
                            self._speech_active = False
                            self._silence_chunks = 0
                            self._speech_chunks = 0
                            self._candidate_chunks = 0
                            self._blocked_speech_chunks = 0
                    elif self._speech_active:
                        self._silence_chunks += 1
                        if self._silence_chunks >= TWILIO_SILENCE_END_CHUNKS:
                            await self.manager.handle_message(
                                self.ws,
                                self.session,
                                json.dumps({"type": "audio_end", "sample_rate": 16000, "source": "twilio"}),
                            )
                            await self.manager._broadcast(self.call_id, {
                                "event": "audio_activity",
                                "source": "twilio",
                                "status": "speech_ended",
                                "rms": rms,
                            })
                            self._speech_active = False
                            self._silence_chunks = 0
                            self._speech_chunks = 0
                            self._candidate_chunks = 0
                            self._blocked_speech_chunks = 0
                    
                elif event == "stop":
                    if self.session and self._speech_active:
                        await self.manager.handle_message(
                            self.ws,
                            self.session,
                            json.dumps({"type": "audio_end", "sample_rate": 16000, "source": "twilio"}),
                        )
                    logger.info(f"Twilio Call Stopped: StreamSid={self.stream_sid}")
                    break

        except WebSocketDisconnect:
            logger.info("Twilio WebSocket disconnected.")
        except Exception as exc:
            logger.error(f"Error in Twilio handler: {exc}")
        finally:
            if self.session:
                await self.manager.disconnect(self.ws, self.session.call_id)

    async def send_tts(self, text: str) -> None:
        """Helper to send a quick TTS response directly through Twilio before the engine processes it."""
        # This is a stub for custom greeting, in reality the TTS comes from the VerificationEngine
        # and gets broadcasted. We need to intercept the broadcast in main/call_handler to send audio to twilio.
        pass
