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
from fastapi import WebSocket, WebSocketDisconnect

from app.ws.call_handler import get_manager

logger = logging.getLogger("samvaad.twilio_handler")

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
        self._ratecv_state = None
        self._pre_roll_frames: list[bytes] = []

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
                    assistant_speaking = bool(self.call_id and self.manager.is_assistant_speaking(self.call_id))
                    speech_threshold = 120 if assistant_speaking else 22
                    is_speech = rms > speech_threshold
                    self._pre_roll_frames.append(pcm_16k)
                    self._pre_roll_frames = self._pre_roll_frames[-5:]

                    if is_speech and not self._speech_active:
                        await self.manager._broadcast(self.call_id, {
                            "event": "audio_activity",
                            "source": "twilio",
                            "status": "speech_started",
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
                                    "barge_in": False,
                                }),
                            )

                    if is_speech or self._speech_active:
                        msg = {
                            "type": "audio_frame",
                            "data": base64.b64encode(pcm_16k).decode("utf-8"),
                            "sample_rate": 16000,
                            "source": "twilio",
                            "rms": rms,
                            "barge_in": bool(is_speech and rms >= 90),
                        }
                        await self.manager.handle_message(self.ws, self.session, json.dumps(msg))

                    if is_speech:
                        self._speech_active = True
                        self._silence_chunks = 0
                        self._speech_chunks += 1

                        # Demo latency guard: don't wait for a long natural pause on PSTN.
                        if self._speech_chunks >= 70:
                            await self.manager.handle_message(
                                self.ws,
                                self.session,
                                json.dumps({"type": "audio_end", "sample_rate": 16000}),
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
                    elif self._speech_active:
                        self._silence_chunks += 1
                        if self._silence_chunks >= 8:
                            await self.manager.handle_message(
                                self.ws,
                                self.session,
                                json.dumps({"type": "audio_end", "sample_rate": 16000}),
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
                    
                elif event == "stop":
                    if self.session and self._speech_active:
                        await self.manager.handle_message(
                            self.ws,
                            self.session,
                            json.dumps({"type": "audio_end", "sample_rate": 16000}),
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
