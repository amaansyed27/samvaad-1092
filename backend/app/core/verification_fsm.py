"""
Verification State Machine — The 1092 Verification Loop
=========================================================
This is the heart of Samvaad 1092. It drives every call through a strict
lifecycle of **Verified Understanding**:

    ┌──────┐    ┌────────┐    ┌───────┐    ┌─────────┐    ┌─────────┐
    │ INIT │──▶│ LISTEN │──▶│ SCRUB │──▶│ ANALYZE │──▶│ RESTATE │
    └──────┘    └────────┘    └───────┘    └─────────┘    └────┬────┘
                                                              │
                                                              ▼
                                                   ┌──────────────────┐
                                                   │ WAIT_FOR_CONFIRM │
                                                   └────────┬─────────┘
                                                        ┌────┴────┐
                                                        ▼         ▼
                                                  ┌──────────┐ ┌───────────────┐
                                                  │ VERIFIED │ │ HUMAN_TAKEOVER│
                                                  └──────────┘ └───────────────┘

Transitions are guarded: the FSM enforces that states can only advance
through the valid lifecycle. Invalid transitions raise `InvalidTransition`.

At any point, if AcousticGuardian reports CRITICAL distress OR confidence
is below threshold, the FSM jumps directly to HUMAN_TAKEOVER.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings
from app.core.acoustic_guardian import get_guardian
from app.core.llm_swarm import get_factory
from app.core.pii_scrubber import get_scrubber
from app.models import (
    AnalysisResult,
    CallSession,
    DistressLevel,
    VerificationState,
)

logger = logging.getLogger("samvaad.verification_fsm")

# ── Valid state transitions ──────────────────────────────────────────────────
_TRANSITIONS: dict[VerificationState, set[VerificationState]] = {
    VerificationState.INIT: {VerificationState.LISTEN, VerificationState.HUMAN_TAKEOVER},
    VerificationState.LISTEN: {VerificationState.SCRUB, VerificationState.HUMAN_TAKEOVER},
    VerificationState.SCRUB: {VerificationState.ANALYZE, VerificationState.HUMAN_TAKEOVER},
    VerificationState.ANALYZE: {VerificationState.RESTATE, VerificationState.HUMAN_TAKEOVER},
    VerificationState.RESTATE: {VerificationState.WAIT_FOR_CONFIRM, VerificationState.HUMAN_TAKEOVER},
    VerificationState.WAIT_FOR_CONFIRM: {VerificationState.VERIFIED, VerificationState.LISTEN, VerificationState.HUMAN_TAKEOVER},
    VerificationState.VERIFIED: set(),  # terminal
    VerificationState.HUMAN_TAKEOVER: set(),  # terminal
}


class InvalidTransition(Exception):
    """Raised when a state transition is not allowed."""


# ── Prompt Templates ─────────────────────────────────────────────────────────

_SENTIMENT_PROMPT = """\
You are an emergency call sentiment analyser for the Karnataka 1092 Helpline.
Analyse the following transcript and return ONLY a JSON object:
{
  "sentiment": "distressed|calm|panicked|angry|confused",
  "confidence": 0.0-1.0,
  "language_detected": "kannada|hindi|english|mixed"
}
Be precise. This is a life-safety system."""

_ANALYSIS_PROMPT = """\
You are an expert emergency dispatcher for the Karnataka 1092 Helpline.
You handle calls in Kannada, Hindi, and English. Analyse this scrubbed
transcript and return ONLY a JSON object:
{
  "emergency_type": "medical|fire|accident|crime|natural_disaster|domestic_violence|other",
  "location_hint": "any location clues from the caller",
  "severity": "critical|high|medium|low",
  "sentiment": "distressed|calm|panicked|angry|confused",
  "key_details": ["detail1", "detail2"],
  "cultural_context": "any dialect or cultural nuances relevant to responders",
  "confidence": 0.0-1.0
}
Be thorough but concise. Lives depend on accuracy."""

_RESTATE_PROMPT = """\
You are a compassionate emergency call assistant for the Karnataka 1092 Helpline.
Based on the analysis below, generate a SHORT restatement in the SAME LANGUAGE
the caller used. This will be spoken back to the caller for verification.

Format: "I understand that [situation]. Is that correct?"
Translate to the caller's language if not English.
Keep it under 50 words. Be empathetic but clear."""


# ══════════════════════════════════════════════════════════════════════════════
# Verification Engine
# ══════════════════════════════════════════════════════════════════════════════

class VerificationEngine:
    """
    Drives a CallSession through the 1092 Verification Loop.

    Each `advance_*` method transitions the session to the next state,
    performs the required processing, and returns an event dict for the
    dashboard WebSocket.
    """

    def __init__(self) -> None:
        self._guardian = get_guardian()
        self._scrubber = get_scrubber()
        self._factory = get_factory()

    def _transition(
        self, session: CallSession, target: VerificationState
    ) -> None:
        """Validate and execute a state transition."""
        current = VerificationState(session.state)
        allowed = _TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidTransition(
                f"Cannot transition from {current.value} → {target.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        session.state = target.value
        logger.info(
            "Call %s: %s → %s", session.call_id, current.value, target.value
        )

    def force_takeover(self, session: CallSession, reason: str) -> dict:
        """
        Emergency bypass — jump to HUMAN_TAKEOVER from any state.
        Used when AcousticGuardian detects CRITICAL distress.
        """
        session.state = VerificationState.HUMAN_TAKEOVER.value
        logger.warning(
            "Call %s: FORCED HUMAN_TAKEOVER — %s", session.call_id, reason
        )
        return {
            "event": "SAFE_HUMAN_TAKEOVER",
            "reason": reason,
            "distress_score": session.distress_score,
        }

    # ── Phase: INIT → LISTEN ─────────────────────────────────────────────

    def start_listening(self, session: CallSession) -> dict:
        """Transition to LISTEN state — system is ready for audio."""
        self._transition(session, VerificationState.LISTEN)
        return {"event": "state_change", "state": "LISTEN"}

    # ── Phase: LISTEN → SCRUB ────────────────────────────────────────────

    async def process_audio(
        self, session: CallSession, audio_bytes: bytes
    ) -> dict:
        """
        Process an audio chunk: distress analysis + transcription stub.

        In production, this would integrate a real-time ASR service.
        For the hackathon, we simulate transcription and focus on the
        distress detection + verification pipeline.
        """
        # Run Acoustic Guardian
        distress = await self._guardian.analyse(audio_bytes)
        session.distress_score = distress["score"]
        session.distress_level = distress["level"]

        # CRITICAL DISTRESS → immediate takeover
        if distress["should_takeover"]:
            return self.force_takeover(
                session,
                f"Acoustic distress score {distress['score']:.2f} ≥ {settings.distress_threshold}",
            )

        return {
            "event": "audio_processed",
            "distress": distress,
        }

    def receive_transcript(
        self, session: CallSession, transcript: str
    ) -> dict:
        """
        Receive a transcript chunk (from ASR) and transition to SCRUB.
        """
        session.raw_transcript += " " + transcript.strip()
        self._transition(session, VerificationState.SCRUB)
        return {"event": "state_change", "state": "SCRUB"}

    # ── Phase: SCRUB → ANALYZE ───────────────────────────────────────────

    def scrub(self, session: CallSession) -> dict:
        """
        Run PII scrubber on the raw transcript.
        SECURITY: This MUST complete before any LLM call.
        """
        clean, entities = self._scrubber.scrub(session.raw_transcript)
        session.scrubbed_transcript = clean
        session.pii_entities_found = entities
        self._transition(session, VerificationState.ANALYZE)
        return {
            "event": "state_change",
            "state": "ANALYZE",
            "pii_count": len(entities),
        }

    # ── Phase: ANALYZE → RESTATE ─────────────────────────────────────────

    async def analyse(self, session: CallSession) -> dict:
        """
        Run the LLM cascade to extract sentiment and emergency analysis.

        Cascade order:
            1. Groq (fast sentiment)
            2. Gemini Flash (analysis)
            3. DeepSeek (cultural nuance fallback)
        """
        transcript = session.scrubbed_transcript

        # ── Step 1: Fast sentiment via Groq/Flash ────────────────────────
        try:
            sentiment_text, sent_log = await self._factory.cascade_generate(
                system_prompt=_SENTIMENT_PROMPT,
                user_message=transcript,
                purpose="sentiment",
                providers=["groq", "gemini"],
                max_tokens=256,
            )
            sentiment_data = _safe_json_parse(sentiment_text)
            session.sentiment = sentiment_data.get("sentiment", "unknown")
            session.language_detected = sentiment_data.get("language_detected", "unknown")
            session.cascade_log.extend(sent_log)
        except Exception as exc:
            logger.error("Sentiment cascade failed: %s", exc)
            session.sentiment = "unknown"

        # ── Step 2: Deep analysis via DeepSeek/Gemini ────────────────────
        try:
            analysis_text, analysis_log = await self._factory.cascade_generate(
                system_prompt=_ANALYSIS_PROMPT,
                user_message=transcript,
                purpose="analysis",
                providers=["deepseek", "gemini", "groq"],
                max_tokens=1024,
            )
            analysis_data = _safe_json_parse(analysis_text)
            session.analysis_result = AnalysisResult(**analysis_data)
            session.confidence = analysis_data.get("confidence", 0.0)
            session.cascade_log.extend(analysis_log)
        except Exception as exc:
            logger.error("Analysis cascade failed: %s", exc)
            session.confidence = 0.0

        # Low confidence → human takeover
        if session.confidence < 0.5:
            return self.force_takeover(
                session,
                f"Analysis confidence too low: {session.confidence:.2f}",
            )

        self._transition(session, VerificationState.RESTATE)
        return {
            "event": "state_change",
            "state": "RESTATE",
            "analysis": session.analysis_result.model_dump() if session.analysis_result else {},
            "sentiment": session.sentiment,
            "confidence": session.confidence,
        }

    # ── Phase: RESTATE → WAIT_FOR_CONFIRM ────────────────────────────────

    async def restate(self, session: CallSession) -> dict:
        """
        Generate a restatement of the emergency for caller verification.
        """
        context = json.dumps(
            session.analysis_result.model_dump() if session.analysis_result else {},
            ensure_ascii=False,
        )
        restate_input = (
            f"Caller language: {session.language_detected}\n"
            f"Analysis: {context}\n"
            f"Transcript: {session.scrubbed_transcript}"
        )

        try:
            restatement, restate_log = await self._factory.cascade_generate(
                system_prompt=_RESTATE_PROMPT,
                user_message=restate_input,
                purpose="restatement",
                providers=["gemini", "groq"],
                max_tokens=256,
            )
            session.restated_summary = restatement.strip()
            session.cascade_log.extend(restate_log)
        except Exception as exc:
            logger.error("Restatement cascade failed: %s", exc)
            return self.force_takeover(session, f"Restatement failed: {exc}")

        self._transition(session, VerificationState.WAIT_FOR_CONFIRM)
        return {
            "event": "restatement",
            "state": "WAIT_FOR_CONFIRM",
            "restatement": session.restated_summary,
        }

    # ── Phase: WAIT_FOR_CONFIRM → VERIFIED / LISTEN ──────────────────────

    def confirm(self, session: CallSession, confirmed: bool) -> dict:
        """
        Caller confirms or rejects the restatement.

        If confirmed → VERIFIED (terminal success).
        If rejected  → LISTEN (loop back for re-capture).
        """
        session.caller_confirmed = confirmed

        if confirmed:
            self._transition(session, VerificationState.VERIFIED)
            return {
                "event": "VERIFIED",
                "state": "VERIFIED",
                "summary": session.restated_summary,
                "confidence": session.confidence,
            }
        else:
            # Rejection loops back to LISTEN for re-capture
            self._transition(session, VerificationState.LISTEN)
            return {
                "event": "state_change",
                "state": "LISTEN",
                "reason": "Caller rejected restatement — re-listening",
            }


# ── Utilities ────────────────────────────────────────────────────────────────

def _safe_json_parse(text: str) -> dict[str, Any]:
    """Extract JSON from LLM output that might include markdown fences."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (the fences)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON output: %s", text[:200])
        return {}
