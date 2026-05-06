"""
Verification State Machine — The 1092 Verification Loop
=========================================================
This is the heart of Samvaad 1092. It drives every call through a strict
lifecycle of **Verified Understanding**:

    ┌──────┐    ┌────────┐    ┌───────┐    ┌─────────┐    ┌────────┐
    │ INIT │──▶│ LISTEN  │──▶│ SCRUB │──▶│ ANALYZE │──▶│ RESTATE │
    └──────┘    └────────┘    └───────┘    └─────────┘    └───┬────┘
                                                              │
                                                              ▼
                                                   ┌──────────────────┐
                                                   │ WAIT_FOR_CONFIRM │
                                                   └────────┬─────────┘
                                                        ┌───┴─────┐
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
    VerificationState.RESTATE: {VerificationState.WAIT_FOR_CONFIRM, VerificationState.LISTEN, VerificationState.HUMAN_TAKEOVER},
    VerificationState.WAIT_FOR_CONFIRM: {VerificationState.VERIFIED, VerificationState.LISTEN, VerificationState.HUMAN_TAKEOVER},
    VerificationState.VERIFIED: set(),  # terminal
    VerificationState.HUMAN_TAKEOVER: set(),  # terminal
}


class InvalidTransition(Exception):
    """Raised when a state transition is not allowed."""


# ── Prompt Templates ─────────────────────────────────────────────────────────

_ANALYSIS_PROMPT = """\
You are an expert civic grievance dispatcher for the Karnataka 1092 Helpline.
You handle calls in Kannada, Hindi, and English. Analyse this scrubbed
transcript and the provided Acoustic Distress Score.

Determine the grievance details. If the caller did not provide enough detail (e.g. they just said "power cut" but no location, or "no water" but no area), you must set "needs_clarification" to true.

Return ONLY a JSON object:
{
  "emergency_type": "power_outage|water_supply|waste_management|road_damage|streetlights|noise_disturbance|animal_control|other",
  "department": "BESCOM|BBMP|BWSSB|POLICE|FIRE|BMTC|RTO|OTHER",
  "location_hint": "exact location or landmark",
  "severity": "high|medium|low",
  "priority": "HIGH|MEDIUM|LOW",
  "sentiment": "frustrated|annoyed|calm|confused|angry",
  "language_detected": "kannada|hindi|english|mixed",
  "key_details": ["detail1", "detail2"],
  "cultural_context": "any dialect or cultural nuances relevant to responders",
  "semantic_distress_score": 0.0-1.0,
  "needs_clarification": true,
  "requires_immediate_takeover": false,
  "confidence": 0.0-1.0
}
Use the Acoustic Distress Score as a hint: if the text is calm but the mic is loud, semantic_distress should be low.
Be thorough but concise. Lives depend on accuracy."""

_RESTATE_PROMPT = """\
You are a civic grievance assistant for the Karnataka 1092 Helpline.
Based on the analysis below, generate a SHORT response in the SAME LANGUAGE the caller used.

If "needs_clarification" is true:
Politely ask the caller for the missing details (like their location or landmark) so you can log the ticket with the specific department.

If "needs_clarification" is false:
Restate the issue and ask for confirmation to log the ticket. Example: "I am logging a ticket with BESCOM for the power cut in Indiranagar. Should I proceed?"

Translate to the caller's language if not English. Keep it under 40 words. Be empathetic but professional."""

_CONFIRMATION_PROMPT = """\
You are an emergency intent analyser. The AI assistant just restated the emergency
and asked if it was correct. Based on the user's response, determine if they
confirmed (said yes/correct/true) or rejected (said no/wrong/false).

Return ONLY a JSON object:
{
  "confirmed": true/false,
  "confidence": 0.0-1.0
}"""

_DISPATCH_PROMPT = """\
You are a civic grievance dispatcher. The caller has just confirmed their issue.
Generate a final reassurance message in their language (English/Hindi/Kannada).
Tell them that their ticket has been logged with the appropriate department and action will be taken.
IMPORTANT: You MUST include their Ticket ID in the message.
Keep it under 30 words.
Example: "Your ticket has been logged with BESCOM under ID A1B2C3. They will resolve the issue soon. Thank you."
"""



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
        Process an audio chunk: distress analysis.
        """
        # Run Acoustic Guardian
        distress = await self._guardian.analyse(audio_bytes)
        # Store latest acoustic distress to be used as context in semantic analysis
        session.distress_score = distress["score"]
        session.distress_level = distress["level"]

        # NOTE: We no longer force an immediate takeover just on acoustic signals.
        # This prevents bad mics from breaking the loop. 
        # The LLM will decide semantic distress based on Acoustic Score + Transcript.

        return {
            "event": "audio_processed",
            "distress": distress,
        }

    async def receive_transcript(
        self, session: CallSession, transcript: str
    ) -> dict:
        """
        Receive a transcript chunk.
        If in LISTEN -> Move to SCRUB.
        If in WAIT_FOR_CONFIRM -> Auto-check for confirmation.
        """
        current_state = VerificationState(session.state)
        
        if current_state == VerificationState.WAIT_FOR_CONFIRM:
            # Automated confirmation check
            try:
                conf_text, _ = await self._factory.cascade_generate(
                    system_prompt=_CONFIRMATION_PROMPT,
                    user_message=f"Restatement: {session.restated_summary}\nCaller Response: {transcript}",
                    purpose="confirmation",
                    providers=["groq", "gemini"],
                    max_tokens=64,
                )
                conf_data = _safe_json_parse(conf_text)
                if conf_data.get("confirmed") and conf_data.get("confidence", 0) > 0.6:
                    return await self.confirm(session, True)
                elif not conf_data.get("confirmed") and conf_data.get("confidence", 0) > 0.6:
                    return await self.confirm(session, False)
            except Exception as exc:
                logger.error("Auto-confirmation failed: %s", exc)
            
            # If auto-confirmation fails or is ambiguous, just stay in WAIT_FOR_CONFIRM
            return {"event": "transcript_received", "transcript": transcript, "note": "Ambiguous confirmation"}

        # Normal loop
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
        acoustic_score = session.distress_score or 0.0

        # ── Deep analysis via DeepSeek/Groq/Gemini ────────────────────
        try:
            analysis_prompt_input = (
                f"Acoustic Distress Score (0=calm, 1=screaming/noise): {acoustic_score:.2f}\n"
                f"Transcript: {transcript}"
            )
            analysis_text, analysis_log = await self._factory.cascade_generate(
                system_prompt=_ANALYSIS_PROMPT,
                user_message=analysis_prompt_input,
                purpose="analysis",
                providers=["groq", "openrouter", "gemini", "or-hy3", "or-oss-120b", "or-nano", "deepseek"],
                max_tokens=1024,
            )
            analysis_data = _safe_json_parse(analysis_text)
            session.analysis_result = AnalysisResult(**analysis_data)
            session.confidence = analysis_data.get("confidence", 0.0)
            session.sentiment = analysis_data.get("sentiment", "unknown")
            session.language_detected = analysis_data.get("language_detected", "unknown")
            
            if analysis_data.get("department"):
                session.department_assigned = analysis_data["department"]
            if analysis_data.get("priority"):
                session.priority = analysis_data["priority"]
            session.cascade_log.extend(analysis_log)
        except Exception as exc:
            logger.error("Analysis cascade failed: %s", exc)
            session.confidence = 0.0

        # Check for ML Routing correction (Active Learning Loop)
        if session.department_assigned != "UNASSIGNED":
            final_dept = session.analysis_result.department if session.analysis_result else None
            # If the Heavy LLM disagrees with the Fast ML (or Fast ML was UNKNOWN)
            if final_dept and final_dept != "OTHER" and final_dept != session.department_assigned:
                logger.info(f"LLM Correction detected: ML said {session.department_assigned}, LLM said {final_dept}")
                try:
                    from app.core.database import save_ml_training_data
                    # Create a fire-and-forget task so we don't block the call flow
                    import asyncio
                    asyncio.create_task(save_ml_training_data(
                        session.call_id, 
                        transcript, 
                        final_dept, 
                        "LLM"
                    ))
                except Exception as e:
                    logger.error(f"Failed to save ML training data: {e}")

        # High semantic distress → human takeover
        if session.analysis_result and session.analysis_result.requires_immediate_takeover:
            return self.force_takeover(
                session,
                f"Semantic analysis requested immediate takeover (Semantic Distress: {session.analysis_result.semantic_distress_score:.2f})",
            )

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
                providers=["groq", "openrouter", "gemini", "or-hy3", "or-oss-120b", "or-nano", "deepseek"],
                max_tokens=256,
            )
            session.restated_summary = restatement.strip()
            session.cascade_log.extend(restate_log)
        except Exception as exc:
            logger.error("Restatement cascade failed: %s", exc)
            return self.force_takeover(session, f"Restatement failed: {exc}")

        # If we need clarification, we loop back to LISTEN instead of waiting for a YES/NO confirmation
        needs_clarification = False
        if session.analysis_result and session.analysis_result.needs_clarification:
            needs_clarification = True
            
        next_state = VerificationState.LISTEN if needs_clarification else VerificationState.WAIT_FOR_CONFIRM
        self._transition(session, next_state)
        
        return {
            "event": "restatement",
            "state": next_state.value,
            "restatement": session.restated_summary,
        }

    # ── Phase: WAIT_FOR_CONFIRM → VERIFIED / LISTEN ──────────────────────

    async def confirm(self, session: CallSession, confirmed: bool) -> dict:
        """
        Caller confirms or rejects the restatement.
        If confirmed -> VERIFIED + generate dispatch message.
        """
        session.caller_confirmed = confirmed

        if confirmed:
            self._transition(session, VerificationState.VERIFIED)
            
            # Generate final dispatch reassurance
            dispatch_msg = "An ambulance has been dispatched. Please stay on the line."
            try:
                res, _ = await self._factory.cascade_generate(
                    system_prompt=_DISPATCH_PROMPT,
                    user_message=f"Context: {session.restated_summary}\nLanguage: {session.language_detected}\nTicket ID: {session.call_id[:6]}",
                    purpose="dispatch_feedback",
                    providers=["groq", "gemini"],
                    max_tokens=128
                )
                dispatch_msg = res.strip()
            except Exception:
                pass

            return {
                "event": "VERIFIED",
                "state": "VERIFIED",
                "summary": session.restated_summary,
                "dispatch_message": dispatch_msg,
                "confidence": session.confidence,
            }
        else:
            # Rejection loops back to LISTEN
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
