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
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("samvaad.sarvam_bridge")


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
        pace: float = 1.0,
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

        payload = {
            "text": text[:2500],  # V3 limit
            "target_language_code": lang,
            "speaker": spk,
            "model": self._model,
            "pace": pace,
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


# ── Singletons ───────────────────────────────────────────────────────────────

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
