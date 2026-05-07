"""
Sarvam Speech Bridge — Indian DPI STT + TTS Integration
==========================================================
Integrates Sarvam AI's Saaras V3 (STT) and Bulbul V3 (TTS) APIs
for production-grade Indic speech processing.

Architecture:
    ┌──────────────┐      ┌──────────────┐
    │  Browser Mic  │──▶  │ Sarvam Saaras │──▶  Transcript (kn/hi/en)
    │  (PCM 16kHz)  │      │   V3 (STT)    │
    └──────────────┘      └──────────────┘

    ┌──────────────┐      ┌──────────────┐
    │  Restatement  │──▶  │ Sarvam Bulbul │──▶  Audio (base64 wav)
    │   (text)      │      │  V3 (TTS)     │
    └──────────────┘      └──────────────┘

STT Modes (Saaras V3):
    - transcribe: Native script transcription
    - translate:  Translate to English
    - codemix:    English words in English, Indic in native script

SECURITY: Audio bytes are processed through AcousticGuardian BEFORE
          reaching Sarvam. PII scrubbing happens AFTER transcription,
          BEFORE any LLM call.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets
from websockets.exceptions import WebSocketException

from app.config import settings

logger = logging.getLogger("samvaad.sarvam_bridge")


def _sarvam_headers() -> dict[str, str]:
    return {
        "api-subscription-key": settings.sarvam_api_key,
        "Api-Subscription-Key": settings.sarvam_api_key,
    }


class SarvamSTT:
    """
    Sarvam Saaras V3 — Speech-to-Text via REST API.

    Sends audio chunks to Sarvam's REST endpoint for transcription.
    Supports Kannada, Hindi, English, and code-mixed speech.
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url="https://api.sarvam.ai",
            headers={
                "api-subscription-key": settings.sarvam_api_key,
            },
            timeout=30.0,
        )
        self._model = settings.sarvam_stt_model
        self._mode = settings.sarvam_stt_mode
        logger.info(
            "SarvamSTT initialised: model=%s mode=%s",
            self._model, self._mode,
        )

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        language_code: str = "unknown",
    ) -> dict[str, Any]:
        """
        Transcribe audio bytes via Sarvam Saaras REST API.

        Parameters
        ----------
        audio_bytes : bytes
            Raw audio (WAV, PCM 16kHz, etc.)
        language_code : str
            BCP-47 code (e.g., "kn-IN", "hi-IN") or "unknown" for auto-detect.

        Returns
        -------
        dict with keys:
            transcript      – str (the transcribed text)
            language_code   – str (detected language BCP-47)
            language_prob   – float (confidence 0-1)
        """
        if not settings.sarvam_api_key:
            logger.warning("Sarvam API key not set — returning empty transcript")
            return {"transcript": "", "language_code": "unknown", "language_prob": 0.0}

        # Build WAV in-memory for the multipart upload
        wav_buffer = io.BytesIO(audio_bytes)
        wav_buffer.name = "audio.wav"

        try:
            files = {"file": ("audio.wav", wav_buffer, "audio/wav")}
            data: dict[str, str] = {
                "model": self._model,
            }
            if self._mode:
                data["mode"] = self._mode
            if language_code != "unknown":
                data["language_code"] = language_code

            resp = await self._http.post(
                "/speech-to-text-translate",
                files=files,
                data=data,
            )
            resp.raise_for_status()
            result = resp.json()

            transcript = result.get("transcript", "")
            lang = result.get("language_code", "unknown")
            prob = result.get("language_probability", 0.0)

            logger.info(
                "Sarvam STT: lang=%s prob=%.2f len=%d",
                lang, prob or 0.0, len(transcript),
            )
            return {
                "transcript": transcript,
                "language_code": lang,
                "language_prob": prob or 0.0,
            }

        except httpx.HTTPStatusError as exc:
            logger.error("Sarvam STT HTTP error %s: %s", exc.response.status_code, exc.response.text)
            return {"transcript": "", "language_code": "unknown", "language_prob": 0.0}
        except Exception as exc:
            logger.exception("Sarvam STT failed: %s", exc)
            return {"transcript": "", "language_code": "unknown", "language_prob": 0.0}

    async def connect_stream(
        self,
        *,
        language_code: str = "en-IN",
        sample_rate: int = 16000,
        high_vad_sensitivity: bool = True,
    ) -> "SarvamSTTStream":
        stream = SarvamSTTStream(
            language_code=language_code if language_code != "unknown" else "en-IN",
            model=self._model,
            mode=self._mode or "transcribe",
            sample_rate=sample_rate,
            high_vad_sensitivity=high_vad_sensitivity,
        )
        await stream.connect()
        return stream


class SarvamSTTStream:
    """Low-level Sarvam streaming STT WebSocket wrapper."""

    def __init__(
        self,
        *,
        language_code: str,
        model: str,
        mode: str,
        sample_rate: int,
        high_vad_sensitivity: bool,
    ) -> None:
        self.language_code = language_code
        self.sample_rate = sample_rate
        params = {
            "language-code": language_code,
            "model": model,
            "mode": mode,
            "sample_rate": str(sample_rate),
            "input_audio_codec": "pcm_s16le",
            "high_vad_sensitivity": str(high_vad_sensitivity).lower(),
            "vad_signals": "true",
            "flush_signal": "true",
        }
        self._url = f"wss://api.sarvam.ai/speech-to-text/ws?{urlencode(params)}"
        self._ws = None

    async def connect(self) -> None:
        if not settings.sarvam_api_key:
            raise RuntimeError("Sarvam API key not set")
        self._ws = await websockets.connect(
            self._url,
            additional_headers=_sarvam_headers(),
            ping_interval=20,
            ping_timeout=20,
            max_size=4 * 1024 * 1024,
        )

    async def send_pcm(self, pcm_bytes: bytes) -> None:
        if self._ws is None:
            raise RuntimeError("Sarvam STT stream is not connected")
        payload = {
            "audio": {
                "data": base64.b64encode(pcm_bytes).decode("utf-8"),
                "sample_rate": self.sample_rate,
                "encoding": "pcm_s16le",
            }
        }
        await self._ws.send(json.dumps(payload))

    async def flush(self) -> None:
        if self._ws is None:
            return
        for payload in ({"type": "flush"}, {"flush": True}):
            try:
                await self._ws.send(json.dumps(payload))
                return
            except WebSocketException:
                raise
            except Exception:
                continue

    async def recv(self) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("Sarvam STT stream is not connected")
        raw = await self._ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {"type": "raw", "data": raw}

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


class SarvamTTS:
    """
    Sarvam Bulbul V3 — Text-to-Speech via REST API.

    Converts restatement text into natural, expressive speech.
    Returns base64-encoded WAV audio for browser playback.
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url="https://api.sarvam.ai",
            headers={
                "api-subscription-key": settings.sarvam_api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._model = settings.sarvam_tts_model
        self._speaker = settings.sarvam_tts_speaker
        self._language = settings.sarvam_tts_language
        logger.info(
            "SarvamTTS initialised: model=%s speaker=%s lang=%s",
            self._model, self._speaker, self._language,
        )

    async def synthesise(
        self,
        text: str,
        *,
        target_language: str | None = None,
        speaker: str | None = None,
        pace: float | None = None,
        output_audio_codec: str | None = None,
        speech_sample_rate: int | None = None,
    ) -> dict[str, Any]:
        """
        Convert text to speech via Sarvam Bulbul REST API.

        Parameters
        ----------
        text : str
            Text to synthesise (max 2500 chars for bulbul:v3).
        target_language : str
            BCP-47 language code (e.g., "kn-IN").
        speaker : str
            Voice name (e.g., "shubh", "ritu", "kavitha").
        pace : float
            Speech speed (0.5–2.0 for V3).

        Returns
        -------
        dict with keys:
            audio_base64 – str (base64-encoded WAV)
            request_id   – str
        """
        if not settings.sarvam_api_key:
            logger.warning("Sarvam API key not set — returning empty audio")
            return {"audio_base64": "", "request_id": ""}

        lang = target_language or self._language
        spk = speaker or self._speaker
        speech_pace = pace if pace is not None else settings.sarvam_tts_pace
        codec = output_audio_codec or "wav"
        sample_rate = speech_sample_rate or settings.sarvam_tts_sample_rate

        payload = {
            "text": text[:2500],  # V3 limit
            "target_language_code": lang,
            "speaker": spk,
            "model": self._model,
            "pace": speech_pace,
            "temperature": settings.sarvam_tts_temperature,
            "speech_sample_rate": sample_rate,
            "output_audio_codec": codec,
            "enable_preprocessing": True,
        }

        try:
            resp = await self._http.post("/text-to-speech", json=payload)
            resp.raise_for_status()
            result = resp.json()

            audios = result.get("audios", [])
            audio_b64 = audios[0] if audios else ""
            request_id = result.get("request_id", "")

            logger.info(
                "Sarvam TTS: lang=%s speaker=%s audio_len=%d",
                lang, spk, len(audio_b64),
            )
            return {
                "audio_base64": audio_b64,
                "request_id": request_id,
            }

        except httpx.HTTPStatusError as exc:
            logger.error("Sarvam TTS HTTP error %s: %s", exc.response.status_code, exc.response.text)
            return {"audio_base64": "", "request_id": ""}
        except Exception as exc:
            logger.exception("Sarvam TTS failed: %s", exc)
            return {"audio_base64": "", "request_id": ""}

    async def stream_synthesise(
        self,
        text: str,
        *,
        target_language: str | None = None,
        speaker: str | None = None,
        pace: float | None = None,
        output_audio_codec: str | None = None,
        speech_sample_rate: int | None = None,
    ):
        """
        Yield streaming TTS chunks. Falls back to REST if the WebSocket path fails.
        Each yielded dict has audio_base64, content_type, codec, and sample_rate.
        """
        if not settings.sarvam_api_key:
            logger.warning("Sarvam API key not set — no streaming audio")
            return

        lang = target_language or self._language
        spk = speaker or self._speaker
        speech_pace = pace if pace is not None else settings.sarvam_tts_pace
        codec = output_audio_codec or settings.sarvam_tts_output_codec
        sample_rate = speech_sample_rate or settings.sarvam_tts_sample_rate
        normalized = _normalize_tts_text(text)

        url = "wss://api.sarvam.ai/text-to-speech/ws?model=bulbul:v3&send_completion_event=true"
        first_audio_seen = False
        try:
            async with websockets.connect(
                url,
                additional_headers=_sarvam_headers(),
                ping_interval=20,
                ping_timeout=20,
                max_size=8 * 1024 * 1024,
            ) as ws:
                await ws.send(json.dumps({
                    "type": "config",
                    "data": {
                        "speaker": spk,
                        "target_language_code": lang,
                        "pace": speech_pace,
                        "temperature": settings.sarvam_tts_temperature,
                        "min_buffer_size": 20,
                        "max_chunk_length": 120,
                        "speech_sample_rate": sample_rate,
                        "output_audio_codec": codec,
                    },
                }))
                await ws.send(json.dumps({"type": "text", "data": {"text": normalized}}))
                await ws.send(json.dumps({"type": "flush"}))

                while True:
                    timeout = 4.0 if not first_audio_seen else 8.0
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="ignore")
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if message.get("type") == "audio":
                        data = message.get("data") or {}
                        audio = data.get("audio") or data.get("chunk") or ""
                        if audio:
                            first_audio_seen = True
                            yield {
                                "audio_base64": audio,
                                "content_type": data.get("content_type") or _codec_content_type(codec),
                                "codec": codec,
                                "sample_rate": sample_rate,
                            }
                    elif message.get("type") == "event":
                        event_data = message.get("data") or {}
                        if event_data.get("event_type") == "final":
                            break
                    elif message.get("type") == "error":
                        raise RuntimeError(str(message))
        except Exception as exc:
            if first_audio_seen:
                logger.warning("Sarvam streaming TTS ended after partial audio: %s", exc)
                return
            logger.warning("Sarvam streaming TTS failed, falling back to REST: %s", exc)
            fallback = await self.synthesise(
                normalized,
                target_language=lang,
                speaker=spk,
                pace=speech_pace,
                output_audio_codec="wav",
                speech_sample_rate=sample_rate,
            )
            if fallback.get("audio_base64"):
                yield {
                    "audio_base64": fallback["audio_base64"],
                    "content_type": "audio/wav",
                    "codec": "wav",
                    "sample_rate": sample_rate,
                }


# ── Singletons ───────────────────────────────────────────────────────────────

def _normalize_tts_text(text: str) -> str:
    """Keep generated speech light and predictable for a call-centre voice."""
    cleaned = " ".join(text.replace("\n", " ").split())
    cleaned = cleaned.replace("1092-", "one zero nine two, ")
    cleaned = cleaned.replace("1092", "one zero nine two")
    return cleaned[:900]


def _codec_content_type(codec: str) -> str:
    return {
        "pcm": "audio/pcm",
        "mulaw": "audio/basic",
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "opus": "audio/opus",
        "aac": "audio/aac",
    }.get(codec, "application/octet-stream")


_stt: SarvamSTT | None = None
_tts: SarvamTTS | None = None


def get_stt() -> SarvamSTT:
    global _stt
    if _stt is None:
        _stt = SarvamSTT()
    return _stt


def get_tts() -> SarvamTTS:
    global _tts
    if _tts is None:
        _tts = SarvamTTS()
    return _tts
