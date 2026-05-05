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
from typing import Any

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
                    pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
                    
                    # Initialize buffer and counters if not present
                    if not hasattr(self, "_audio_buffer"):
                        self._audio_buffer = bytearray()
                        self._silence_chunks = 0
                        
                    # Calculate RMS energy for VAD (Silence Gating)
                    rms = audioop.rms(pcm_16k, 2)
                    
                    # 150 is a common threshold for background noise vs speech
                    is_speech = rms > 150

                    if is_speech:
                        self._audio_buffer.extend(pcm_16k)
                        self._silence_chunks = 0
                    elif len(self._audio_buffer) > 0:
                        self._audio_buffer.extend(pcm_16k)
                        self._silence_chunks += 1
                    
                    # Flush buffer if we hit 0.5s of silence (25 chunks of 20ms) 
                    # OR if the buffer gets too long (e.g., 4 seconds = 128000 bytes)
                    should_flush = (self._silence_chunks >= 25 and len(self._audio_buffer) > 0) or len(self._audio_buffer) >= 128000
                    
                    if should_flush:
                        import io
                        import wave
                        
                        wav_io = io.BytesIO()
                        with wave.open(wav_io, 'wb') as wav_file:
                            wav_file.setnchannels(1)
                            wav_file.setsampwidth(2) # 16-bit PCM
                            wav_file.setframerate(16000)
                            wav_file.writeframes(bytes(self._audio_buffer))
                        
                        wav_bytes = wav_io.getvalue()
                        
                        msg = {
                            "type": "audio",
                            "data": base64.b64encode(wav_bytes).decode("utf-8")
                        }
                        await self.manager.handle_message(self.ws, self.session, json.dumps(msg))
                        self._audio_buffer.clear()
                        self._silence_chunks = 0
                    
                elif event == "stop":
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
