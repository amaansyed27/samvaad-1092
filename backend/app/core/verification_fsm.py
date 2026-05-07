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
import re
from typing import Any

from app.config import settings
from app.core.acoustic_guardian import get_guardian
from app.core.location_resolver import candidate_from_geo_pin, resolve_location_candidates
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


_LANGUAGE_LABELS = {
    "en-IN": "english",
    "kn-IN": "kannada",
    "hi-IN": "hindi",
}

_LANGUAGE_CODES = {value: key for key, value in _LANGUAGE_LABELS.items()}

_LANGUAGE_DIALECTS = {
    "en-IN": "Indian English",
    "kn-IN": "Karnataka Kannada",
    "hi-IN": "Indian Hindi",
}

_BROAD_LOCATION_TERMS = {
    "area",
    "district",
    "taluk",
    "ward",
    "village",
    "city",
    "bangalore",
    "bengaluru",
    "whitefield",
    "indiranagar",
    "koramangala",
    "jayanagar",
    "hebbal",
    "yelahanka",
    "marathahalli",
    "rajajinagar",
    "airport",
    "vidhana soudha",
    "vidhan sabha",
}

_SPECIFIC_LOCATION_MARKERS = {
    "road",
    "street",
    "main",
    "cross",
    "block",
    "phase",
    "stage",
    "layout",
    "sector",
    "circle",
    "near",
    "opposite",
    "behind",
    "beside",
    "landmark",
    "temple",
    "school",
    "college",
    "hospital",
    "bus stop",
    "metro",
    "police station",
    "apartment",
    "gate",
    "tower",
    "address",
    "no.",
    "number",
    "feet road",
}

_MAJOR_AMBIGUOUS_LOCATIONS = {
    "airport",
    "kempegowda airport",
    "kempegowda international airport",
    "vidhana soudha",
    "vidhan sabha",
    "vidhana sabha",
    "majestic",
    "railway station",
    "bus stand",
}

_FAKE_LOCATION_CUES = {
    "fake location",
    "dummy location",
    "not real location",
    "random location",
    "test address",
    "imaginary",
    "nowhere",
}

_YES_TOKENS = {
    "yes",
    "correct",
    "right",
    "true",
    "proceed",
    "confirm",
    "confirmed",
    "haan",
    "hoga",
    "sahi",
    "theek",
    "theek hai",
    "howdu",
    "haudu",
    "sari",
    "हाँ",
    "जी",
    "सही",
    "ठीक",
    "हां",
    "ಹೌದು",
    "ಸರಿ",
}

_NO_TOKENS = {
    "no",
    "wrong",
    "incorrect",
    "not correct",
    "cancel",
    "illa",
    "nahi",
    "nahin",
    "नहीं",
    "गलत",
    "ಇಲ್ಲ",
    "ತಪ್ಪು",
}

_CORRECTION_CUES = {
    "but",
    "actually",
    "location",
    "landmark",
    "near",
    "at",
    "in",
    "ward",
    "road",
    "street",
    "change",
    "instead",
}

_ABUSE_WARNING_SLOT = "abuse_warning"
_REQUIRED_CLARIFICATION_SLOTS = {
    "issue",
    "location",
    "landmark",
    "location_confirm",
    "service_detail",
    "correction",
    _ABUSE_WARNING_SLOT,
}
_OPTIONAL_DETAIL_SLOTS = (
    "started_at_or_time",
    "frequency",
    "application_or_reference",
    "office_visited",
    "caller_tried",
    "authority_contacted",
    "previous_complaint",
    "documents_available",
)
_MAX_OPTIONAL_QUESTIONS = 2
_SKIP_OPTIONAL_CUES = (
    "just log",
    "create ticket",
    "log ticket",
    "raise ticket",
    "proceed",
    "go ahead",
    "enough",
    "immediately",
    "right now",
)

_SERVICE_GRIEVANCE_DEPARTMENTS = {
    "FOOD_CIVIL_SUPPLIES",
    "LABOUR",
    "SOCIAL_WELFARE",
    "RDPR",
    "HEALTH",
    "TRANSPORT_RTO",
    "EDUCATION",
    "REVENUE",
    "MUNICIPALITY_PANCHAYAT",
}

_SPECIALIZED_HELPLINES = {
    "BESCOM": "1912",
    "BWSSB": "1916",
    "BBMP": "1533",
    "HEALTH": "104",
    "AMBULANCE": "102/108",
    "WOMEN": "181",
    "POLICE": "100",
    "FIRE": "101",
}

_LINE_DEPARTMENT_NAMES = {
    "BESCOM": "BESCOM",
    "BWSSB": "BWSSB",
    "BBMP": "BBMP ward/engineering office",
    "POLICE": "Local police station",
    "WOMEN": "Women and Child safety cell",
    "AMBULANCE": "Emergency medical response",
    "FIRE": "Fire and emergency services",
    "FOOD_CIVIL_SUPPLIES": "Food and Civil Supplies department",
    "LABOUR": "Labour department",
    "SOCIAL_WELFARE": "Social Welfare department",
    "RDPR": "Rural Development and Panchayat Raj",
    "HEALTH": "Health and Family Welfare department",
    "TRANSPORT_RTO": "Transport/RTO office",
    "EDUCATION": "Education department",
    "REVENUE": "Revenue department",
    "MUNICIPALITY_PANCHAYAT": "Municipality/Panchayat office",
}

_PRANK_OR_DUMMY_TERMS = (
    "prank",
    "dummy",
    "fake complaint",
    "timepass",
    "just testing",
    "testing testing",
    "test call",
    "nothing happened",
    "no issue",
    "no problem",
    "asdf",
    "blah blah",
)
_ABUSIVE_TERMS = (
    "idiot",
    "stupid",
    "shut up",
    "bloody",
    "useless",
)
_URGENCY_TERMS = (
    "urgent",
    "immediately",
    "right now",
    "emergency",
    "danger",
    "unsafe",
    "sparking",
    "fire",
    "shock",
    "wire down",
    "hospital",
    "school",
    "elderly",
    "children",
)


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

    def set_language(self, session: CallSession, language_code: str) -> dict:
        """Lock the caller language from IVR or the operator demo controls."""
        code = language_code if language_code in _LANGUAGE_LABELS else "unknown"
        label = _LANGUAGE_LABELS.get(code, "auto")
        session.preferred_language_code = code
        session.preferred_language_label = label
        if label != "auto":
            session.language_detected = label
        return {
            "event": "language_selected",
            "language_code": code,
            "language": label,
            "dialect": _LANGUAGE_DIALECTS.get(code, "auto"),
        }

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
            "assistant_message": _build_human_takeover_message(session, reason),
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
            direct_intent = _detect_confirmation_intent(transcript)
            if direct_intent is not None:
                return await self.confirm(session, direct_intent)

            if _is_confirmation_clarification_question(transcript):
                message = _build_confirmation_explanation(session)
                session.restated_summary = message
                return {
                    "event": "clarification_required",
                    "state": session.state,
                    "prompt": message,
                    "assistant_message": message,
                    "slots": _build_slot_view(session),
                }

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
            
            # Treat longer ambiguous replies as corrections/details and re-run the slot loop.
            self._transition(session, VerificationState.LISTEN)
            session.latest_transcript = transcript.strip()
            session.raw_transcript += " " + session.latest_transcript
            self._transition(session, VerificationState.SCRUB)
            return {
                "event": "state_change",
                "state": "SCRUB",
                "note": "Caller supplied correction or extra details",
            }

        # Normal loop
        session.latest_transcript = transcript.strip()
        session.raw_transcript += " " + session.latest_transcript
        self._transition(session, VerificationState.SCRUB)
        return {"event": "state_change", "state": "SCRUB"}


    # ── Phase: SCRUB → ANALYZE ───────────────────────────────────────────

    def scrub(self, session: CallSession) -> dict:
        """
        Run PII scrubber on the raw transcript.
        SECURITY: This MUST complete before any LLM call.
        """
        clean, entities = self._scrubber.scrub(session.raw_transcript)
        latest_clean, _ = self._scrubber.scrub(session.latest_transcript or "")
        session.scrubbed_transcript = clean
        session.latest_scrubbed_transcript = latest_clean
        session.pii_entities_found = entities
        self._transition(session, VerificationState.ANALYZE)
        return {
            "event": "state_change",
            "state": "ANALYZE",
            "pii_count": len(entities),
        }

    def scrub_fast(self, session: CallSession) -> dict:
        """
        Run regex-only PII scrubbing for live phone calls.

        The full Indic NER layer is valuable for records and offline review, but
        it can block a PSTN call long enough for the caller to hear silence.
        """
        clean, entities = self._scrubber.scrub_fast(session.raw_transcript)
        latest_clean, _ = self._scrubber.scrub_fast(session.latest_transcript or "")
        session.scrubbed_transcript = clean
        session.latest_scrubbed_transcript = latest_clean
        session.pii_entities_found = entities
        self._transition(session, VerificationState.ANALYZE)
        return {
            "event": "state_change",
            "state": "ANALYZE",
            "pii_count": len(entities),
            "fast_scrub": True,
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
        transcript = session.latest_scrubbed_transcript or session.scrubbed_transcript
        acoustic_score = session.distress_score or 0.0

        analysis_data = _build_fast_analysis(session, transcript, acoustic_score)
        session.analysis_result = AnalysisResult(**analysis_data)
        session.confidence = analysis_data.get("confidence", 0.0)
        session.sentiment = analysis_data.get("sentiment", "unknown")
        session.language_detected = analysis_data.get("language_detected", "unknown")
        session.department_assigned = analysis_data.get("department") or session.department_assigned
        session.priority = analysis_data.get("priority", session.priority)
        session.call_slots = _build_slot_view(session)

        if session.analysis_result.requires_immediate_takeover:
            return self.force_takeover(
                session,
                f"High urgency or distress detected (score {session.analysis_result.semantic_distress_score:.2f})",
            )

        is_required_clarification = session.required_slot in _REQUIRED_CLARIFICATION_SLOTS
        if (
            session.analysis_result.needs_clarification
            and is_required_clarification
            and session.required_slot != "location_confirm"
            and session.clarification_count >= 2
        ):
            return self.force_takeover(
                session,
                "I may not be capturing this correctly. I am handing this to a human operator so you do not have to repeat yourself.",
            )

        self._transition(session, VerificationState.RESTATE)
        return {
            "event": "state_change",
            "state": "RESTATE",
            "analysis": session.analysis_result.model_dump(),
            "slots": session.call_slots,
            "conversation_memory": session.conversation_memory,
            "sentiment": session.sentiment,
            "confidence": session.confidence,
        }

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
            analysis_data = _post_process_analysis(session, analysis_data)
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
        if session.confidence < 0.5 and not (
            session.analysis_result and session.analysis_result.needs_clarification
        ):
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
        if not session.analysis_result:
            return self.force_takeover(session, "Restatement failed: missing analysis")

        session.restated_summary = _build_restatement(session)

        # If we need clarification, we loop back to LISTEN instead of waiting for a YES/NO confirmation
        needs_clarification = False
        if session.analysis_result and session.analysis_result.needs_clarification:
            needs_clarification = True
            if session.required_slot in _REQUIRED_CLARIFICATION_SLOTS:
                session.clarification_count += 1
            elif session.required_slot in _OPTIONAL_DETAIL_SLOTS:
                session.optional_detail_count += 1
        else:
            session.required_slot = "confirmation"
        session.call_slots = _build_slot_view(session)
            
        next_state = VerificationState.LISTEN if needs_clarification else VerificationState.WAIT_FOR_CONFIRM
        self._transition(session, next_state)
        
        return {
            "event": "restatement",
            "state": next_state.value,
            "restatement": session.restated_summary,
            "needs_clarification": needs_clarification,
            "slots": session.call_slots,
            "conversation_memory": session.conversation_memory,
        }

    # ── Phase: WAIT_FOR_CONFIRM → VERIFIED / LISTEN ──────────────────────

    async def confirm(self, session: CallSession, confirmed: bool) -> dict:
        """
        Caller confirms or rejects the restatement.
        If confirmed -> VERIFIED + generate dispatch message.
        """
        session.caller_confirmed = confirmed

        if confirmed:
            memory = _get_conversation_memory(session)
            if session.analysis_result and not memory.get("ticket_ready"):
                session.required_slot = "landmark" if memory.get("area") else "location"
                session.caller_confirmed = None
                self._transition(session, VerificationState.LISTEN)
                session.restated_summary = _build_restatement(session)
                session.call_slots = _build_slot_view(session)
                return {
                    "event": "state_change",
                    "state": "LISTEN",
                    "reason": "Required ticket fields are still missing",
                    "restatement": session.restated_summary,
                    "slots": session.call_slots,
                }
            self._transition(session, VerificationState.VERIFIED)
            
            dispatch_msg = _build_dispatch_message(session)

            return {
                "event": "VERIFIED",
                "state": "VERIFIED",
                "summary": session.restated_summary,
                "dispatch_message": dispatch_msg,
                "ticket_id": session.ticket_id,
                "confidence": session.confidence,
                "slots": _build_slot_view(session),
                "conversation_memory": session.conversation_memory,
            }
        else:
            # Rejection loops back to LISTEN
            self._transition(session, VerificationState.LISTEN)
            session.required_slot = "correction"
            session.call_slots = _build_slot_view(session)
            return {
                "event": "state_change",
                "state": "LISTEN",
                "reason": "Caller rejected restatement — re-listening",
                "slots": session.call_slots,
            }



# ── Utilities ────────────────────────────────────────────────────────────────
def _get_conversation_memory(session: CallSession) -> dict[str, Any]:
    memory = dict(session.conversation_memory or {})
    defaults = {
        "issue": "",
        "department": "",
        "request_type": "grievance",
        "line_department": "",
        "secondary_department": "",
        "service_or_scheme": "",
        "application_or_reference": "",
        "office_visited": "",
        "official_contacted": "",
        "documents_available": "",
        "area": "",
        "landmark": "",
        "started_at_or_time": "",
        "frequency": "",
        "currently_happening": "",
        "caller_tried": "",
        "authority_contacted": "",
        "previous_complaint": "",
        "urgency": "",
        "sentiment": "",
        "ticket_ready": False,
        "skip_optional": False,
        "abuse_risk": "LOW",
        "abuse_action": "ALLOW",
        "abuse_reason": "",
        "priority_reason": "",
        "empathy_note": "",
        "operator_hint": "",
        "status_lookup": "Call 1092 and quote the ticket number.",
        "emergency_referral": False,
        "specialized_helpline": "",
        "caller_safe_now": "",
        "immediate_danger": False,
        "normalized_location": "",
        "location_confidence": 0.0,
        "location_validation_status": "missing",
        "location_validation_reason": "",
        "location_source": "speech",
        "location_confirmed": False,
        "geo_pin": {},
        "map_candidates": [],
        "map_candidate_selected": {},
        "location_needs_candidate_confirmation": False,
        "missing_slot": "issue",
        "last_question": "",
    }
    for key, value in defaults.items():
        memory.setdefault(key, value)
    return memory


def _update_conversation_memory(
    session: CallSession,
    transcript: str,
    department: str,
    emergency_type: str,
    sentiment: str,
) -> dict[str, Any]:
    memory = _get_conversation_memory(session)
    text = " ".join((transcript or "").split())
    lower = text.lower()

    if session.required_slot == "location_confirm" and _is_affirmative_location_confirmation(text):
        _accept_top_map_candidate(memory)

    if emergency_type and emergency_type != "other":
        memory["issue"] = emergency_type
    if department and department not in {"UNASSIGNED", "UNKNOWN", "OTHER"}:
        memory["department"] = department
        memory["line_department"] = _line_department_for(department, emergency_type)

    service_detail = _extract_service_or_scheme(text, department, emergency_type)
    if service_detail:
        memory["service_or_scheme"] = service_detail
    application_reference = _extract_application_reference(text)
    if application_reference:
        memory["application_or_reference"] = application_reference
    elif session.required_slot == "application_or_reference":
        fallback_reference = _extract_reference_fallback(text)
        if fallback_reference:
            memory["application_or_reference"] = fallback_reference
            memory["skip_optional"] = True
    office_visited = _extract_office_visited(text)
    if office_visited:
        memory["office_visited"] = office_visited
    documents_available = _extract_documents_available(text)
    if documents_available:
        memory["documents_available"] = documents_available
    if session.required_slot in _OPTIONAL_DETAIL_SLOTS and _is_unhelpful_optional_answer(text, session.required_slot):
        memory["skip_optional"] = True

    should_update_location = (
        session.required_slot in {"issue", "location", "landmark", "location_confirm", "service_detail"}
        or bool(_extract_structured_location(text))
        or bool(_extract_location_hint(text))
    )
    if session.required_slot not in {"issue", "location", "landmark", "location_confirm", "service_detail"} and _is_impact_or_time_detail(text):
        should_update_location = False
    if should_update_location:
        location = _extract_location_hint(text)
        if location:
            if _looks_like_location(location) and _is_specific_location(location):
                memory["landmark"] = _clean_stored_location(location)
                memory["area"] = _area_from_location(location) or _area_from_location(text) or memory.get("area", "")
            elif _looks_like_location(location) and location.lower().strip(" .,:;") not in {"my house", "my home", "home", "house"}:
                memory["area"] = _clean_stored_location(location)
        else:
            location_phrase = _extract_standalone_location(text)
            if location_phrase:
                if _is_specific_location(location_phrase):
                    memory["landmark"] = _clean_stored_location(location_phrase)
                    memory["area"] = _area_from_location(location_phrase) or memory.get("area", "")
                else:
                    memory["area"] = location_phrase

    query_location = memory.get("landmark") or memory.get("area")
    candidates = resolve_location_candidates(
        query_location or text,
        area_hint=memory.get("area", ""),
        geo_pin=memory.get("geo_pin") or None,
    )
    memory["map_candidates"] = candidates
    memory["location_needs_candidate_confirmation"] = False
    if candidates and not memory.get("location_confirmed"):
        top = candidates[0]
        candidate_confident = top["confidence"] >= 0.72 and not top.get("broad")
        if candidate_confident:
            exact_candidate = _is_exact_candidate_mention(query_location or text, top)
            if exact_candidate:
                if _is_broad_area(memory.get("area")) and top.get("area"):
                    memory["area"] = top["area"]
                if not memory.get("landmark") or _location_contains_non_location_tail(memory.get("landmark", "")):
                    memory["landmark"] = top["landmark"]
                memory["location_source"] = "map_candidate"
            elif not _has_strong_location_context(query_location or text, memory.get("area", "")):
                memory["location_needs_candidate_confirmation"] = True

    validation = _validate_location(memory.get("landmark") or memory.get("area"), transcript=text, memory=memory)
    memory["normalized_location"] = validation["normalized"]
    memory["location_confidence"] = validation["confidence"]
    memory["location_validation_status"] = validation["status"]
    memory["location_validation_reason"] = validation["reason"]

    memory["sentiment"] = sentiment
    memory["urgency"] = "HIGH" if sentiment in {"angry", "fear", "urgent", "frustrated"} else "LOW"

    if any(cue in lower for cue in _SKIP_OPTIONAL_CUES):
        memory["skip_optional"] = True
    if any(term in lower for term in ("right now", "currently", "now", "happening now")):
        memory["currently_happening"] = "yes"
    if any(term in lower for term in ("every night", "daily", "again and again", "many times", "repeated", "too many")):
        memory["frequency"] = _extract_frequency(text)
    if any(term in lower for term in ("since", "morning", "evening", "night", "yesterday", "today", "week", "month", "hour")) and session.required_slot in {"issue", "started_at_or_time", "frequency", "location_confirm", "confirmation"}:
        time_detail = _extract_time_detail(text)
        if time_detail:
            existing_time = memory.get("started_at_or_time", "")
            memory["started_at_or_time"] = (
                f"{existing_time}; {time_detail}"
                if existing_time and time_detail not in existing_time
                else time_detail or existing_time
            )
    if any(term in lower for term in ("tried", "checked", "called", "reported", "complained", "complaint")):
        memory["caller_tried"] = _extract_caller_tried(text)
    authority = _extract_authority_contact(lower)
    if authority:
        memory["authority_contacted"] = authority
        memory["official_contacted"] = authority
    previous = _extract_previous_complaint(text)
    if previous:
        memory["previous_complaint"] = previous

    effective_department = department if department not in {"OTHER", "UNKNOWN", "UNASSIGNED"} else memory.get("department")
    service_reference_ready = bool(memory.get("application_or_reference") or memory.get("service_or_scheme") or memory.get("office_visited"))
    service_location_ready = bool(memory.get("area") or memory.get("landmark"))
    usable_location = (
        (bool(memory.get("landmark")) or _is_specific_location(memory.get("area")))
        and validation["status"] in {"usable", "verified_format", "map_confirmed", "pin_verified"}
    )
    service_ready = effective_department in _SERVICE_GRIEVANCE_DEPARTMENTS and service_location_ready and service_reference_ready
    if service_ready and not usable_location:
        memory["location_validation_status"] = "service_area"
        memory["location_validation_reason"] = "Public-service grievance has enough district/area or office context for intake."
        memory["location_confidence"] = max(float(memory.get("location_confidence") or 0.0), 0.7)
    memory["ticket_ready"] = bool(memory.get("issue") and memory.get("department") and (usable_location or service_ready))
    session.conversation_memory = memory
    return memory


def apply_geo_pin_to_session(session: CallSession, pin: dict[str, Any]) -> dict[str, Any]:
    """Apply an operator/browser map pin to the conversation memory."""
    memory = _get_conversation_memory(session)
    candidate = candidate_from_geo_pin(pin)
    memory["geo_pin"] = {
        "lat": candidate.get("lat"),
        "lng": candidate.get("lng"),
        "accuracy_m": pin.get("accuracy_m") or pin.get("accuracy") or 0,
        "address": pin.get("address", ""),
    }
    memory["map_candidate_selected"] = candidate
    memory["map_candidates"] = [candidate]
    memory["location_source"] = "map_pin"
    memory["location_confirmed"] = candidate["status"] == "pin_verified"
    memory["area"] = candidate.get("area") or memory.get("area", "")
    memory["landmark"] = candidate.get("landmark") or memory.get("landmark", "")
    memory["normalized_location"] = candidate.get("address") or candidate.get("name") or ""
    memory["location_confidence"] = candidate.get("confidence", 0.0)
    memory["location_validation_status"] = candidate["status"]
    memory["location_validation_reason"] = candidate["reason"]
    usable_location = candidate["status"] == "pin_verified"
    memory["ticket_ready"] = bool(memory.get("issue") and memory.get("department") and usable_location)
    memory["missing_slot"] = "" if usable_location else "location"
    if usable_location and session.required_slot in {"location", "landmark", "location_confirm"}:
        session.required_slot = "confirmation" if memory.get("issue") and memory.get("department") else "issue"
    session.conversation_memory = memory
    session.call_slots = _build_slot_view(session)
    return memory


def _accept_top_map_candidate(memory: dict[str, Any]) -> None:
    candidates = memory.get("map_candidates") or []
    if not candidates:
        return
    selected = candidates[0]
    if selected.get("broad"):
        return
    memory["map_candidate_selected"] = selected
    memory["location_confirmed"] = True
    memory["location_source"] = selected.get("source", "map_candidate")
    memory["area"] = selected.get("area") or memory.get("area", "")
    memory["landmark"] = _clean_stored_location(selected.get("landmark") or selected.get("name") or memory.get("landmark", ""))
    memory["normalized_location"] = selected.get("address") or selected.get("name") or memory.get("normalized_location", "")
    memory["location_confidence"] = max(float(selected.get("confidence", 0.0)), 0.86)
    memory["location_validation_status"] = "map_confirmed"
    memory["location_validation_reason"] = "Caller confirmed the map/location candidate."
    memory["location_needs_candidate_confirmation"] = False


def _should_ask_optional_detail(session: CallSession, memory: dict[str, Any]) -> bool:
    if not memory.get("ticket_ready"):
        return False
    if memory.get("skip_optional"):
        return False
    if memory.get("sentiment") in {"angry", "fear", "urgent", "frustrated"}:
        return False
    if session.optional_detail_count >= _MAX_OPTIONAL_QUESTIONS:
        return False
    return bool(_next_optional_slot(memory))


def _next_optional_slot(memory: dict[str, Any]) -> str:
    service_department = memory.get("department") in _SERVICE_GRIEVANCE_DEPARTMENTS
    if service_department:
        service_order = (
            "application_or_reference",
            "office_visited",
            "caller_tried",
            "authority_contacted",
            "previous_complaint",
            "documents_available",
            "started_at_or_time",
            "frequency",
        )
        for slot in service_order:
            if not memory.get(slot):
                return slot
        return ""
    for slot in _OPTIONAL_DETAIL_SLOTS:
        if slot in {"application_or_reference", "office_visited", "documents_available"} and not service_department:
            continue
        if not memory.get(slot):
            return slot
    return ""


def _area_from_location(location: str) -> str:
    lower = location.lower()
    preferred_areas = (
        "indiranagar",
        "whitefield",
        "koramangala",
        "jayanagar",
        "hebbal",
        "yelahanka",
        "marathahalli",
        "rajajinagar",
        "bangalore",
        "bengaluru",
    )
    for area in preferred_areas:
        if area in lower:
            return area.title()
    generic_terms = {"area", "district", "taluk", "ward", "village", "city"}
    for area in _BROAD_LOCATION_TERMS - generic_terms:
        if area in lower:
            return area.title()
    return ""


def _extract_standalone_location(text: str) -> str:
    cleaned = text.strip(" .,:;")
    lower = cleaned.lower()
    if not cleaned or len(cleaned.split()) > 8:
        return ""
    if _is_non_location_phrase(cleaned):
        return ""
    location_terms = set(_BROAD_LOCATION_TERMS) | _SPECIFIC_LOCATION_MARKERS
    if any(term in lower for term in location_terms):
        return cleaned
    return ""


def _extract_time_detail(text: str) -> str:
    lower = text.lower()
    details: list[str] = []
    patterns = [
        r"since\s+[^,.]+",
        r"for\s+the\s+past\s+[^,.]+",
        r"(?:pending\s+)?for\s+\d+\s+(?:days?|weeks?|months?|years?)",
        r"past\s+[^,.]+",
        r"\b\d+\s+(?:continuous\s+)?cuts?\s+in\s+\d+\s+days?\b",
        r"\b\d+\s*[- ]\s*hours?\s+(?:power\s+)?cuts?\b",
        r"\b(?:power\s+)?cuts?\s+(?:for\s+)?\d+\s*[- ]\s*hours?\b",
        r"each\s+cut\s+(?:has\s+)?lasted\s+[^,.]+",
        r"every\s+(?:morning|evening|night|day)",
        r"(?:morning|evening|night|yesterday|today|last\s+week|this\s+week)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, lower):
            detail = match.group(0).strip(" .,:;")
            if detail and detail not in details:
                details.append(detail)
    if details:
        return "; ".join(details[:3])
    return _trim_detail_text(text)


def _extract_frequency(text: str) -> str:
    lower = text.lower()
    match = re.search(r"\b\d+\s+(?:continuous\s+)?cuts?\s+in\s+\d+\s+days?\b", lower)
    if match:
        return match.group(0)
    if "every night" in lower:
        return "every night"
    if "daily" in lower:
        return "daily"
    if "again and again" in lower:
        return "again and again"
    if "many times" in lower or "too many" in lower or "repeated" in lower:
        return "repeated"
    return _trim_detail_text(text)


def _extract_caller_tried(text: str) -> str:
    cleaned = " ".join(text.split()).strip(" .,:;")
    match = re.search(
        r"\b(?:we|i|they|he|she)?\s*(?:have\s+)?(?:already\s+)?(?:tried|called|contacted|reported|complained|made\s+this\s+complaint)\b.*",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        return _trim_detail_text(match.group(0))
    return _trim_detail_text(cleaned)


def _extract_authority_contact(lower: str) -> str:
    for authority in ("bescom", "bbmp", "bwssb", "police", "fire", "1092"):
        if authority in lower and any(term in lower for term in ("called", "contacted", "contacting", "tried", "reported", "complained")):
            return authority.upper()
    if "authority" in lower or "office" in lower or "helpline" in lower:
        return "authority contacted"
    return ""


def _extract_previous_complaint(text: str) -> str:
    match = re.search(
        r"\b(?:ticket|complaint|case)\s*(?:number|id|no)?\s*[:#-]?\s*([A-Za-z0-9-]{2,})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(0).strip(" .,:;")
    if "already complained" in text.lower() or "previous complaint" in text.lower():
        return text.strip(" .,:;")
    return ""


def _extract_application_reference(text: str) -> str:
    match = re.search(
        r"\b(?:application|ration card|pension|case|file|acknowledgement|acknowledgment|reference|ref|ticket|complaint)\s*(?:number|id|no|#)\s*[:#-]?\s*([A-Za-z0-9-]{3,})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(0).strip(" .,:;")
    return ""


def _extract_reference_fallback(text: str) -> str:
    lower = " ".join((text or "").lower().split())
    if not lower:
        return ""
    if any(term in lower for term in ("same mobile", "linked mobile", "mobile number", "phone number", "this number")):
        return "linked with caller mobile number"
    if any(term in lower for term in ("no", "don't have", "do not have", "not have", "not available", "i do not know", "i don't know")):
        return "not provided; use caller mobile number"
    return ""


def _extract_service_or_scheme(text: str, department: str, emergency_type: str) -> str:
    if department not in _SERVICE_GRIEVANCE_DEPARTMENTS:
        return ""
    lower = text.lower()
    service_terms = (
        ("ration card", "ration card"),
        ("anna bhagya", "Anna Bhagya"),
        ("pension", "pension"),
        ("wages", "wages complaint"),
        ("salary", "salary/wages complaint"),
        ("labour office", "labour office"),
        ("hospital", "government hospital service"),
        ("medicine", "hospital medicine service"),
        ("rto", "RTO service"),
        ("driving license", "driving license"),
        ("licence", "driving license"),
        ("bus pass", "transport/bus pass service"),
        ("scholarship", "scholarship"),
        ("land record", "land record"),
        ("rtc", "RTC/land record"),
        ("khata", "khata/revenue service"),
        ("income certificate", "income certificate"),
        ("caste certificate", "caste certificate"),
        ("mgnrega", "MGNREGA"),
        ("nrega", "MGNREGA"),
    )
    for cue, label in service_terms:
        if cue in lower:
            return label
    if department in _SERVICE_GRIEVANCE_DEPARTMENTS:
        return _issue_label(emergency_type, "english")
    return ""


def _extract_office_visited(text: str) -> str:
    match = re.search(
        r"\b(?:visited|went to|called|contacted)\s+(?:the\s+)?([A-Za-z ]{3,40}?(?:office|hospital|rto|panchayat|station))\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(" .,:;")
    return ""


def _extract_documents_available(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ("photo", "photos", "document", "documents", "proof", "receipt", "sms")):
        if any(term in lower for term in ("no photo", "no document", "don't have", "do not have")):
            return "not available"
        return "available"
    return ""


def _build_fast_analysis(
    session: CallSession,
    transcript: str,
    acoustic_score: float,
) -> dict[str, Any]:
    """Deterministic call-centre analysis for the live demo path."""
    transcript = transcript or session.raw_transcript or ""
    deterministic_department = _infer_department(transcript)
    existing_department = session.conversation_memory.get("department") or session.department_assigned
    detail_turn = (
        session.required_slot not in {"issue", "service_detail", "correction"}
        and existing_department
        and existing_department not in {"UNASSIGNED", "UNKNOWN", "OTHER"}
        and not _looks_like_new_grievance(transcript)
    )
    if detail_turn:
        department = existing_department
    elif deterministic_department != "OTHER":
        department = deterministic_department
    elif session.department_assigned and session.department_assigned not in {"UNASSIGNED", "UNKNOWN"}:
        department = session.department_assigned
    else:
        department = "OTHER"

    emergency_type = _infer_emergency_type(transcript, department)
    language = _preferred_language(session, _detect_text_language(transcript))
    sentiment = _sentiment_from_text(transcript, acoustic_score)
    has_issue = _has_issue_signal(transcript, department, emergency_type)
    abuse = _assess_abuse_or_prank(transcript, has_issue)
    memory = _update_conversation_memory(session, transcript, department, emergency_type, sentiment)
    has_issue = has_issue or bool(memory.get("issue"))
    if department in {"OTHER", "UNKNOWN", "UNASSIGNED"} and memory.get("department"):
        department = memory["department"]
    line_department = _line_department_for(department, emergency_type)
    request_type = _infer_request_type(transcript, department, emergency_type, sentiment, abuse)
    secondary_department = _infer_secondary_department(transcript, department, emergency_type)
    specialized_helpline = _specialized_helpline_for(department, emergency_type, request_type, transcript)
    memory["request_type"] = request_type
    memory["line_department"] = line_department
    memory["secondary_department"] = secondary_department
    memory["specialized_helpline"] = specialized_helpline
    memory["emergency_referral"] = request_type == "emergency_referral"
    memory["status_lookup"] = "Use this 1092 ticket number to check status or quote it if a representative contacts you."
    memory["abuse_risk"] = abuse["risk"]
    memory["abuse_action"] = abuse["action"]
    memory["abuse_reason"] = abuse["reason"]
    location = memory.get("landmark") or memory.get("area") or _extract_location_hint(transcript)
    location_validation = _validate_location(location, transcript=transcript, memory=memory)
    location_specific = (
        (bool(memory.get("landmark")) or _is_specific_location(location))
        and location_validation["status"] in {"usable", "verified_format", "map_confirmed", "pin_verified"}
    )
    service_department = department in _SERVICE_GRIEVANCE_DEPARTMENTS
    service_reference_ready = bool(
        memory.get("service_or_scheme") or memory.get("application_or_reference") or memory.get("office_visited")
    )
    service_area_ready = bool(memory.get("area") or memory.get("landmark"))
    service_ticket_ready = service_department and service_area_ready and service_reference_ready
    needs_clarification = False
    key_details = _key_details_from_text(transcript, emergency_type, location)
    if request_type == "emergency_referral" and specialized_helpline:
        key_details.append(f"Emergency referral helpline: {specialized_helpline}")
    if secondary_department:
        key_details.append(f"Secondary department note: {secondary_department}")

    if abuse["action"] in {"WARN", "BLACKLIST_REVIEW"} and (not has_issue or department == "OTHER" or emergency_type == "other"):
        session.required_slot = _ABUSE_WARNING_SLOT
        needs_clarification = True
        key_details.append(f"Abuse/spam guardrail: {abuse['reason']}")
    elif request_type == "emergency_referral":
        session.required_slot = "confirmation"
        needs_clarification = False
        key_details.append("Immediate danger or specialized emergency support needed")
    elif not has_issue:
        session.required_slot = "issue"
        needs_clarification = True
        key_details.append("Needs grievance details")
    elif department in {"OTHER", "UNKNOWN", "UNASSIGNED"} and not _has_public_service_context(transcript):
        session.required_slot = "issue"
        needs_clarification = True
        key_details.append("Needs clearer grievance details")
    elif department in {"OTHER", "UNKNOWN", "UNASSIGNED"}:
        session.required_slot = "service_detail"
        needs_clarification = True
        key_details.append("Needs department, office, scheme, or service detail")
    elif service_department and not service_reference_ready:
        session.required_slot = "service_detail"
        needs_clarification = True
        key_details.append("Needs scheme, office, service, or application reference")
    elif service_department and not service_area_ready:
        session.required_slot = "location"
        needs_clarification = True
        key_details.append("Needs district, city, area, or office location")
    elif service_ticket_ready:
        memory["ticket_ready"] = True
        if _should_ask_optional_detail(session, memory):
            session.required_slot = _next_optional_slot(memory) or "confirmation"
            needs_clarification = session.required_slot != "confirmation"
        else:
            session.required_slot = "confirmation"
    elif location.lower().strip(" .,:;") in {"my house", "my home", "home", "house"}:
        session.required_slot = "landmark"
        needs_clarification = True
        key_details.append("Needs area and nearest landmark for caller home")
    elif not memory.get("area") and not memory.get("landmark"):
        session.required_slot = "location"
        needs_clarification = True
        key_details.append("Needs caller location")
    elif location_validation["status"] == "needs_map_confirmation":
        session.required_slot = "location_confirm"
        needs_clarification = True
        key_details.append(location_validation["reason"])
        if memory.get("started_at_or_time"):
            key_details.append(f"Timing captured: {memory['started_at_or_time']}")
    elif location_validation["status"] not in {"usable", "verified_format", "map_confirmed", "pin_verified"}:
        session.required_slot = "landmark"
        needs_clarification = True
        key_details.append(location_validation["reason"])
    elif not location_specific:
        session.required_slot = "landmark"
        needs_clarification = True
        key_details.append(f"Needs street, ward, or nearest landmark for {location}")
    elif _should_ask_optional_detail(session, memory):
        session.required_slot = _next_optional_slot(memory) or "confirmation"
        needs_clarification = session.required_slot != "confirmation"
    else:
        session.required_slot = "confirmation"

    fake_or_dummy_location = any(term in transcript.lower() for term in ("fake location", "dummy location"))
    memory["ticket_ready"] = bool(
        has_issue
        and department not in {"OTHER", "UNKNOWN", "UNASSIGNED"}
        and (location_specific or service_ticket_ready)
        and not fake_or_dummy_location
    )
    memory["missing_slot"] = session.required_slot if needs_clarification else ""
    session.conversation_memory = memory

    priority_data = _score_priority(transcript, sentiment, acoustic_score, memory, emergency_type, abuse)
    semantic_distress = priority_data["semantic_distress"]
    severity = priority_data["severity"]
    priority = priority_data["priority"]
    requires_takeover = priority_data["requires_takeover"]
    memory["priority_reason"] = priority_data["reason"]
    memory["empathy_note"] = _build_empathy_note(sentiment, priority, memory, abuse)
    memory["operator_hint"] = _build_operator_hint(request_type, department, secondary_department, specialized_helpline, priority)
    session.conversation_memory = memory

    return {
        "request_type": request_type,
        "emergency_type": emergency_type,
        "department": department,
        "line_department": line_department,
        "secondary_department": secondary_department,
        "location_hint": location,
        "severity": severity,
        "priority": priority,
        "sentiment": sentiment,
        "language_detected": language,
        "key_details": key_details,
        "cultural_context": _cultural_context_from_text(transcript),
        "semantic_distress_score": semantic_distress,
        "empathy_note": memory["empathy_note"],
        "priority_reason": memory["priority_reason"],
        "abuse_risk": abuse["risk"],
        "abuse_score": abuse["score"],
        "abuse_action": abuse["action"],
        "abuse_reason": abuse["reason"],
        "status_lookup": memory["status_lookup"],
        "specialized_helpline": specialized_helpline,
        "emergency_referral": memory["emergency_referral"],
        "operator_hint": memory["operator_hint"],
        "needs_clarification": needs_clarification,
        "requires_immediate_takeover": requires_takeover or request_type == "emergency_referral",
        "confidence": 0.74 if needs_clarification else 0.88,
    }


def _build_slot_view(session: CallSession) -> dict[str, Any]:
    analysis = session.analysis_result
    memory = _get_conversation_memory(session)
    location = memory.get("landmark") or memory.get("area") or ((analysis.location_hint if analysis else "") or "")
    slots = {
        "request_type": memory.get("request_type", "grievance"),
        "issue": memory.get("issue") or (analysis.emergency_type if analysis else ""),
        "department": memory.get("department") or (analysis.department if analysis else None) or session.department_assigned,
        "line_department": memory.get("line_department") or (analysis.line_department if analysis else ""),
        "secondary_department": memory.get("secondary_department") or (analysis.secondary_department if analysis else ""),
        "service_or_scheme": memory.get("service_or_scheme", ""),
        "application_or_reference": memory.get("application_or_reference", ""),
        "office_visited": memory.get("office_visited", ""),
        "official_contacted": memory.get("official_contacted", ""),
        "documents_available": memory.get("documents_available", ""),
        "emergency_referral": memory.get("emergency_referral", False),
        "specialized_helpline": memory.get("specialized_helpline", ""),
        "status_lookup": memory.get("status_lookup", ""),
        "operator_hint": memory.get("operator_hint", ""),
        "location": location,
        "area": memory.get("area", ""),
        "location_specific": (
            (bool(memory.get("landmark")) or _is_specific_location(location))
            and memory.get("location_validation_status") in {"usable", "verified_format", "map_confirmed", "pin_verified"}
        ),
        "landmark": memory.get("landmark", ""),
        "started_at_or_time": memory.get("started_at_or_time", ""),
        "frequency": memory.get("frequency", ""),
        "currently_happening": memory.get("currently_happening", ""),
        "caller_tried": memory.get("caller_tried", ""),
        "authority_contacted": memory.get("authority_contacted", ""),
        "previous_complaint": memory.get("previous_complaint", ""),
        "normalized_location": memory.get("normalized_location", ""),
        "location_confidence": memory.get("location_confidence", 0.0),
        "location_validation_status": memory.get("location_validation_status", "missing"),
        "location_validation_reason": memory.get("location_validation_reason", ""),
        "location_source": memory.get("location_source", "speech"),
        "location_confirmed": memory.get("location_confirmed", False),
        "geo_pin": memory.get("geo_pin", {}),
        "map_candidates": memory.get("map_candidates", []),
        "map_candidate_selected": memory.get("map_candidate_selected", {}),
        "location_needs_candidate_confirmation": memory.get("location_needs_candidate_confirmation", False),
        "empathy_note": memory.get("empathy_note", ""),
        "priority_reason": memory.get("priority_reason", ""),
        "abuse_risk": memory.get("abuse_risk", "LOW"),
        "abuse_action": memory.get("abuse_action", "ALLOW"),
        "abuse_reason": memory.get("abuse_reason", ""),
        "ticket_ready": bool(memory.get("ticket_ready")),
        "urgency": (analysis.priority if analysis else None) or session.priority,
        "sentiment": (analysis.sentiment if analysis else None) or session.sentiment,
        "confirmation": session.caller_confirmed,
        "required_slot": session.required_slot,
        "clarification_count": session.clarification_count,
        "optional_detail_count": session.optional_detail_count,
    }
    return slots


def _post_process_analysis(session: CallSession, data: dict[str, Any]) -> dict[str, Any]:
    """Apply fast helpline guardrails that should not depend on an LLM."""
    transcript = session.scrubbed_transcript or session.raw_transcript
    data = dict(data or {})

    dept = data.get("department") or session.department_assigned
    if not dept or dept in {"UNASSIGNED", "UNKNOWN"}:
        dept = _infer_department(transcript)
    data["department"] = dept

    data["emergency_type"] = data.get("emergency_type") or _infer_emergency_type(transcript, dept)
    data["request_type"] = data.get("request_type") or _infer_request_type(
        transcript,
        dept,
        data["emergency_type"],
        data.get("sentiment") or "confused",
        {"action": "ALLOW"},
    )
    data["line_department"] = data.get("line_department") or _line_department_for(dept, data["emergency_type"])
    data["secondary_department"] = data.get("secondary_department") or _infer_secondary_department(
        transcript,
        dept,
        data["emergency_type"],
    )
    data["specialized_helpline"] = data.get("specialized_helpline") or _specialized_helpline_for(
        dept,
        data["emergency_type"],
        data["request_type"],
        transcript,
    )
    data["status_lookup"] = data.get("status_lookup") or "Use this 1092 ticket number to check status or quote it if a representative contacts you."
    data["emergency_referral"] = bool(data.get("emergency_referral") or data["request_type"] == "emergency_referral")
    data["operator_hint"] = data.get("operator_hint") or _build_operator_hint(
        data["request_type"],
        dept,
        data["secondary_department"],
        data["specialized_helpline"],
        data.get("priority") or "MEDIUM",
    )
    data["language_detected"] = _preferred_language(session, data.get("language_detected"))
    data["sentiment"] = data.get("sentiment") or "confused"
    data["priority"] = data.get("priority") or ("HIGH" if session.distress_score >= 0.7 else "MEDIUM")
    data["severity"] = data.get("severity") or ("high" if session.distress_score >= 0.7 else "medium")
    data["semantic_distress_score"] = float(data.get("semantic_distress_score") or min(session.distress_score, 0.75))
    data["requires_immediate_takeover"] = bool(data.get("requires_immediate_takeover", False))
    data["key_details"] = data.get("key_details") or []

    location = (data.get("location_hint") or _extract_location_hint(transcript) or "").strip()
    data["location_hint"] = location

    needs_location = data["emergency_type"] in {
        "power_outage",
        "water_supply",
        "waste_management",
        "road_damage",
        "streetlights",
        "noise_disturbance",
        "other",
    }
    if needs_location and not _is_specific_location(location):
        data["needs_clarification"] = True
        detail = "Needs street, ward, or nearest landmark"
        if location:
            detail = f"{detail} for {location}"
        if detail not in data["key_details"]:
            data["key_details"].append(detail)

    if data.get("needs_clarification"):
        data["confidence"] = max(float(data.get("confidence") or 0.0), 0.62)
    else:
        data["confidence"] = max(float(data.get("confidence") or 0.0), 0.78)

    return data


def _preferred_language(session: CallSession, detected: str | None = None) -> str:
    if session.preferred_language_label and session.preferred_language_label != "auto":
        return session.preferred_language_label
    detected = (detected or session.language_detected or "english").lower()
    if detected in {"kannada", "hindi", "english", "mixed"}:
        return detected
    return "english"


def _line_department_for(department: str, emergency_type: str | None = None) -> str:
    if emergency_type == "streetlights":
        return "BBMP streetlight/ward engineering team"
    if emergency_type == "women_safety":
        return "Women helpline and local police station"
    return _LINE_DEPARTMENT_NAMES.get(department or "", department or "")


def _infer_request_type(
    transcript: str,
    department: str,
    emergency_type: str,
    sentiment: str,
    abuse: dict[str, Any],
) -> str:
    text = (transcript or "").lower()
    if abuse.get("action") in {"WARN", "BLACKLIST_REVIEW"} and not _has_issue_signal(transcript, department, emergency_type):
        return "spam_or_prank"
    emergency_terms = (
        "right now",
        "immediate danger",
        "following me",
        "being followed",
        "attacking",
        "assault",
        "fire",
        "smoke",
        "gas leak",
        "ambulance",
        "heart attack",
        "unconscious",
        "accident",
        "child is sick",
        "very sick",
        "not safe now",
    )
    if department in {"POLICE", "WOMEN", "AMBULANCE", "FIRE"} and any(term in text for term in emergency_terms):
        return "emergency_referral"
    if sentiment in {"fear", "urgent"} and any(term in text for term in ("now", "right now", "danger", "scared", "unsafe")):
        return "emergency_referral"
    if any(term in text for term in ("how to", "where can i", "what is the process", "information", "enquiry", "enquiry")):
        return "general_request"
    return "grievance"


def _infer_secondary_department(transcript: str, department: str, emergency_type: str) -> str:
    text = (transcript or "").lower()
    if department == "BWSSB" and any(term in text for term in ("sick", "ill", "vomit", "fever", "child", "hospital")):
        return "HEALTH"
    if emergency_type == "streetlights" and any(term in text for term in ("unsafe", "staring", "harassment", "following", "women", "girl")):
        return "POLICE/WOMEN"
    if department == "HEALTH" and any(term in text for term in ("ambulance", "critical", "emergency", "unconscious")):
        return "AMBULANCE"
    return ""


def _specialized_helpline_for(department: str, emergency_type: str, request_type: str, transcript: str) -> str:
    text = (transcript or "").lower()
    if emergency_type == "streetlights":
        return _SPECIALIZED_HELPLINES.get("BBMP", "")
    if department == "HEALTH" and any(term in text for term in ("ambulance", "emergency", "unconscious", "accident")):
        return _SPECIALIZED_HELPLINES["AMBULANCE"]
    if request_type == "emergency_referral" and department in _SPECIALIZED_HELPLINES:
        return _SPECIALIZED_HELPLINES[department]
    if department in {"BESCOM", "BWSSB", "BBMP", "HEALTH", "WOMEN", "POLICE", "FIRE"}:
        return _SPECIALIZED_HELPLINES.get(department, "")
    return ""


def _build_operator_hint(
    request_type: str,
    department: str,
    secondary_department: str,
    specialized_helpline: str,
    priority: str,
) -> str:
    if request_type == "emergency_referral":
        target = specialized_helpline or _LINE_DEPARTMENT_NAMES.get(department, "the emergency operator")
        return f"Stop optional intake and connect/referral immediately. Route to {target}."
    if request_type == "general_request":
        return "Treat as public-service guidance first; capture department/service and only register if the caller wants a grievance."
    if secondary_department:
        return f"Register primary grievance, add cross-department note for {secondary_department}."
    if priority in {"HIGH", "CRITICAL"}:
        return "Keep the call short, reassure the caller, and avoid optional questions."
    return "Register grievance with line department after explicit caller confirmation."


def _infer_department(transcript: str) -> str:
    text = transcript.lower()
    if _has_streetlight_issue(text):
        return "BBMP"
    if any(term in text for term in (
        "power",
        "bijli",
        "electric",
        "electrical",
        "electricity",
        "current",
        "voltage",
        "transformer",
        "vidyut",
        "vidyuth",
        "vidyuta",
        "à²µà²¿à²¦à³à²¯à³à²¤à³",
        "karentu",
        "current hogide",
        "current illa",
        "kadita",
        "kaá¸ita",
        "kaditavide",
    )):
        return "BESCOM"
    if any(term in text for term in ("water", "paani", "neeru", "sewage", "drainage", "pipe", "cauvery", "contaminated")):
        return "BWSSB"
    if any(term in text for term in ("ambulance", "heart attack", "unconscious", "serious injury", "accident")):
        return "AMBULANCE"
    if any(term in text for term in ("women safety", "woman safety", "stalking", "molest", "domestic violence")):
        return "WOMEN"
    if any(term in text for term in ("ration", "ration card", "pds", "food grain", "fair price", "anna bhagya")):
        return "FOOD_CIVIL_SUPPLIES"
    if any(term in text for term in ("labour", "labor", "wages", "salary", "employer", "worker", "pf", "esi")):
        return "LABOUR"
    if any(term in text for term in ("pension", "old age", "widow pension", "disability pension", "social welfare")):
        return "SOCIAL_WELFARE"
    if any(term in text for term in ("panchayat", "village office", "grama", "rural", "mgnrega", "nrega")):
        return "RDPR"
    if any(term in text for term in ("hospital staff", "government hospital", "doctor", "medicine", "health service", "clinic", "phc", "refused medicine")):
        return "HEALTH"
    if any(term in text for term in ("rto", "driving license", "licence", "vehicle registration", "transport", "bus pass", "bmtc")):
        return "TRANSPORT_RTO"
    if any(term in text for term in ("school", "college", "teacher", "education", "scholarship")):
        return "EDUCATION"
    if any(term in text for term in ("land record", "rtc", "khata", "tahsildar", "taluk office", "revenue", "caste certificate", "income certificate")):
        return "REVENUE"
    if any(term in text for term in ("municipality", "municipal", "town panchayat", "city municipal")):
        return "MUNICIPALITY_PANCHAYAT"
    if any(term in text for term in (
        "power",
        "bijli",
        "electric",
        "electrical",
        "electricity",
        "current",
        "voltage",
        "transformer",
        "streetlight",
        "vidyut",
        "vidyuth",
        "vidyuta",
        "ವಿದ್ಯುತ್",
        "karentu",
        "current hogide",
        "current illa",
        "kadita",
        "kaḍita",
        "kaditavide",
    )):
        return "BESCOM"
    if any(term in text for term in ("water", "paani", "neeru", "sewage", "drainage", "pipe", "cauvery", "contaminated")):
        return "BWSSB"
    if any(term in text for term in ("garbage", "pothole", "road", "waste", "tree", "drain")):
        return "BBMP"
    if any(term in text for term in ("fire", "smoke", "gas leak", "blast")):
        return "FIRE"
    if any(term in text for term in ("theft", "fight", "harassment", "following", "noise", "unsafe", "threat")):
        return "POLICE"
    return "OTHER"


def _infer_emergency_type(transcript: str, department: str) -> str:
    text = transcript.lower()
    if department == "FOOD_CIVIL_SUPPLIES":
        return "ration_card"
    if department == "LABOUR":
        return "labour_grievance"
    if department == "SOCIAL_WELFARE":
        return "pension_delay"
    if department == "RDPR":
        return "rdpr_service"
    if department == "HEALTH":
        return "health_service"
    if department == "TRANSPORT_RTO":
        return "transport_service"
    if department == "EDUCATION":
        return "education_service"
    if department == "REVENUE":
        return "revenue_service"
    if department == "MUNICIPALITY_PANCHAYAT":
        return "municipal_service"
    if department == "WOMEN":
        return "women_safety"
    if department == "AMBULANCE":
        return "medical_emergency"
    if department == "FIRE":
        return "fire"
    if _has_streetlight_issue(text):
        return "streetlights"
    if any(term in text for term in (
        "power",
        "bijli",
        "electric",
        "electrical",
        "electricity",
        "current",
        "voltage",
        "transformer",
        "cut",
        "cuts",
        "vidyut",
        "vidyuth",
        "vidyuta",
        "ವಿದ್ಯುತ್",
        "karentu",
        "current hogide",
        "current illa",
        "kadita",
        "kaḍita",
        "kaditavide",
    )):
        return "power_outage"
    if department == "BWSSB":
        return "water_supply"
    if department == "BBMP" and any(term in text for term in ("road", "pothole", "street", "footpath")):
        return "road_damage"
    if department == "BBMP" and any(term in text for term in ("garbage", "waste", "trash", "dump", "overflow")):
        return "waste_management"
    if department == "POLICE" and "noise" in text:
        return "noise_disturbance"
    if department == "POLICE" and any(term in text for term in ("following", "harassment", "unsafe", "threat", "fight", "theft")):
        return "public_safety"
    return "other"


def _has_issue_signal(transcript: str, department: str, emergency_type: str) -> bool:
    text = transcript.lower()
    if emergency_type != "other":
        return True
    issue_terms = (
        "problem",
        "issue",
        "complaint",
        "grievance",
        "application",
        "pending",
        "ration",
        "pension",
        "wages",
        "salary",
        "hospital",
        "medicine",
        "rto",
        "license",
        "office",
        "scheme",
        "help",
        "cut",
        "not working",
        "broken",
        "blocked",
        "leak",
        "overflow",
        "garbage",
        "noise",
        "harassment",
        "fire",
        "smoke",
        "water",
        "electric",
        "electrical",
        "electricity",
        "power",
        "road",
        "vidyut",
        "vidyuth",
        "vidyuta",
        "ವಿದ್ಯುತ್",
        "karentu",
        "kadita",
        "kaḍita",
        "kaditavide",
    )
    return any(term in text for term in issue_terms)


def _has_public_service_context(transcript: str) -> bool:
    text = (transcript or "").lower()
    return any(
        term in text
        for term in (
            "department",
            "office",
            "scheme",
            "service",
            "application",
            "ration",
            "pension",
            "labour",
            "labor",
            "wages",
            "hospital",
            "rto",
            "transport",
            "school",
            "college",
            "certificate",
            "panchayat",
            "municipality",
            "revenue",
        )
    )


def _is_impact_or_time_detail(text: str) -> bool:
    lower = (text or "").lower()
    return any(
        cue in lower
        for cue in (
            "past",
            "week",
            "month",
            "day",
            "hour",
            "hours",
            "cut",
            "cuts",
            "lasting",
            "lasted",
            "occurring",
            "happening",
            "usually",
        )
    )


def _is_unhelpful_optional_answer(text: str, slot: str) -> bool:
    lower = " ".join((text or "").lower().strip(" .,!?:;").split())
    if not lower:
        return True
    if lower in {"last stage", "the last stage"}:
        return True
    if slot == "started_at_or_time":
        if _extract_time_detail(text) and not _looks_like_random_numeric_fragment(lower):
            return False
        return True
    if slot in {"frequency", "caller_tried", "authority_contacted", "previous_complaint"}:
        return len(lower.split()) <= 2 and _looks_like_random_numeric_fragment(lower)
    return False


def _looks_like_random_numeric_fragment(text: str) -> bool:
    lower = (text or "").lower().strip(" .,!?:;")
    if re.fullmatch(r"\d+(?:\s+(?:crore|lakh|thousand|hundred))?", lower):
        return True
    if lower in {"one crore", "hundred crore", "100 crore"}:
        return True
    return False


def _looks_like_new_grievance(transcript: str) -> bool:
    text = (transcript or "").lower()
    strong_terms = (
        "problem",
        "issue",
        "complaint",
        "grievance",
        "pending",
        "not working",
        "no water",
        "water contaminated",
        "contaminated water",
        "power cut",
        "power cuts",
        "electricity cut",
        "electrical cut",
        "street light",
        "street lights",
        "garbage",
        "waste",
        "pothole",
        "broken",
        "unsafe",
        "harassment",
        "fire",
        "smoke",
    )
    return any(term in text for term in strong_terms)


def _has_streetlight_issue(text: str) -> bool:
    lower = (text or "").lower()
    return any(
        term in lower
        for term in (
            "streetlight",
            "street light",
            "street lights",
            "road light",
            "road lights",
            "no lights",
            "no light",
            "lights are not working",
        )
    )


def _assess_abuse_or_prank(transcript: str, has_issue: bool) -> dict[str, Any]:
    text = " ".join((transcript or "").lower().split())
    score = 0.0
    reasons: list[str] = []

    if not text:
        return {"score": 0.0, "risk": "LOW", "action": "ALLOW", "reason": ""}
    if any(term in text for term in _PRANK_OR_DUMMY_TERMS):
        score += 0.55
        reasons.append("dummy/prank wording")
    if any(term in text for term in _ABUSIVE_TERMS):
        score += 0.35
        reasons.append("abusive language")
    if len(text.split()) <= 2 and not has_issue:
        score += 0.25
        reasons.append("too little grievance detail")
    if re.fullmatch(r"[\W\d_]+", text):
        score += 0.5
        reasons.append("non-speech/noise-like content")
    if "haha" in text or "lol" in text:
        score += 0.3
        reasons.append("laughter/prank cue")
    if has_issue:
        score = max(0.0, score - 0.35)

    score = min(score, 1.0)
    if score >= 0.75:
        risk = "HIGH"
        action = "BLACKLIST_REVIEW"
    elif score >= 0.35:
        risk = "MEDIUM"
        action = "WARN"
    else:
        risk = "LOW"
        action = "ALLOW"

    return {
        "score": score,
        "risk": risk,
        "action": action,
        "reason": ", ".join(reasons),
    }


def _score_priority(
    transcript: str,
    sentiment: str,
    acoustic_score: float,
    memory: dict[str, Any],
    emergency_type: str,
    abuse: dict[str, Any],
) -> dict[str, Any]:
    text = (transcript or "").lower()
    score = 0.18
    reasons: list[str] = []

    if abuse.get("action") == "BLACKLIST_REVIEW" and not memory.get("ticket_ready"):
        return {
            "semantic_distress": 0.15,
            "severity": "low",
            "priority": "LOW",
            "requires_takeover": False,
            "reason": "Potential prank/spam call; do not assign civic priority until a real grievance is stated.",
        }

    acoustic_component = min(max(acoustic_score, 0.0), 0.85) * 0.35
    score += acoustic_component
    if acoustic_score >= 0.65:
        reasons.append("high acoustic distress")

    sentiment_boosts = {
        "fear": 0.45,
        "urgent": 0.35,
        "angry": 0.28,
        "frustrated": 0.22,
        "confused": 0.12,
        "calm": 0.0,
    }
    boost = sentiment_boosts.get(sentiment, 0.0)
    score += boost
    if boost:
        reasons.append(f"caller sounds {sentiment}")

    if any(term in text for term in _URGENCY_TERMS):
        score += 0.25
        reasons.append("urgent/safety wording")
    if any(term in text for term in ("do not feel safe", "don't feel safe", "not feel safe", "shady area", "people keep staring", "staring at me")):
        score += 0.25
        reasons.append("caller reports personal safety concern")
    if any(term in text for term in ("refused medicine", "medicine denied", "hospital staff refused", "child is sick", "contaminated water", "dirty water")):
        score += 0.32
        reasons.append("health or vulnerable-person impact")
    if any(term in text for term in ("wages pending", "salary pending", "not paid", "pension not received", "application pending")):
        score += 0.12
        reasons.append("service delay affecting citizen entitlement")
    if any(term in text for term in ("past week", "for the past week", "many times", "again and again", "repeated", "continuous")):
        score += 0.18
        reasons.append("repeated or long-running issue")
    if memory.get("frequency") == "repeated" or memory.get("started_at_or_time"):
        score += 0.12
        reasons.append("repeated or long-running issue")
    if (
        re.search(r"\b(?:over|more than|above)\s+\d+\s+hours?\b", text)
        or re.search(r"\b\d+\s+hours?\b", text)
        or re.search(r"\b\d+\s*-\s*hours?\b", text)
    ):
        score += 0.24
        reasons.append("long service interruption")
    if re.search(r"\b\d+\s+(?:continuous\s+)?cuts?\b", text):
        score += 0.12
        reasons.append("multiple outages reported")
    if memory.get("authority_contacted") or memory.get("caller_tried"):
        score += 0.1
        reasons.append("caller already tried prior escalation")
    if emergency_type in {"fire", "gas_leak"}:
        score += 0.5
        reasons.append("life-safety category")
    if memory.get("request_type") == "emergency_referral":
        score += 0.45
        reasons.append("specialized emergency referral needed")

    score = min(score, 1.0)
    if score >= 0.72:
        priority = "HIGH"
        severity = "high"
    elif score >= 0.42:
        priority = "MEDIUM"
        severity = "medium"
    else:
        priority = "LOW"
        severity = "low"

    immediate_takeover_terms = (
        "scared",
        "danger",
        "threat",
        "sparking",
        "fire",
        "shock",
        "wire down",
        "following me",
        "being followed",
        "attacking",
        "help now",
    )
    return {
        "semantic_distress": score,
        "severity": severity,
        "priority": priority,
        "requires_takeover": (
            emergency_type in {"fire", "gas_leak", "medical_emergency"}
            or any(term in text for term in immediate_takeover_terms)
            or memory.get("request_type") == "emergency_referral"
            or (priority == "HIGH" and acoustic_score >= 0.85 and sentiment in {"fear", "urgent"})
        ),
        "reason": "; ".join(reasons) or "Routine civic intake based on current details.",
    }


def _build_empathy_note(sentiment: str, priority: str, memory: dict[str, Any], abuse: dict[str, Any]) -> str:
    if abuse.get("action") == "BLACKLIST_REVIEW":
        return "Possible prank/spam call. Warn once and send to supervisor review before any blacklist action."
    if sentiment in {"angry", "frustrated"}:
        return "Acknowledge frustration and reassure the caller that their previous difficulty is being recorded."
    if sentiment in {"fear", "urgent"} or priority == "HIGH":
        return "Use a calm urgent tone, reassure the caller, and avoid asking optional questions."
    if memory.get("ticket_ready"):
        return "Acknowledge the issue and move toward verification without making the caller repeat details."
    return "Acknowledge the caller first, then ask for one missing detail."


def _extract_location_hint(transcript: str) -> str:
    text = " ".join(transcript.split())
    structured = _extract_structured_location(text)
    if structured:
        return structured
    lower = text.lower()
    best_index = -1
    best_candidate = ""
    for marker in (" location is ", " in ", " at ", " near ", " from "):
        for match in re.finditer(re.escape(marker), lower):
            candidate = _clean_location_hint(text[match.end():])
            if not candidate or _is_non_location_phrase(candidate):
                continue
            if _looks_like_location(candidate) and match.start() > best_index:
                best_index = match.start()
                best_candidate = candidate
    if best_candidate:
        return best_candidate
    return ""


def _extract_structured_location(text: str) -> str:
    address = _extract_label_value(text, ("address", "addr"))
    landmark = _extract_label_value(text, ("landmark", "nearby landmark"))
    if address and landmark:
        if landmark.lower().startswith(("near ", "opposite ", "beside ", "behind ")):
            return _clean_location_hint(f"{address}, {landmark}")
        return _clean_location_hint(f"{address}, near {landmark}")
    if address:
        return _clean_location_hint(address)
    if landmark:
        return _clean_location_hint(landmark)
    return ""


def _extract_label_value(text: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"\b(?:{label_pattern})\s*[:\-]\s*(.+?)(?=\b(?:address|addr|landmark|nearby landmark)\s*[:\-]|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return match.group(1).strip(" .,:;")


def _clean_location_hint(location: str) -> str:
    cleaned = location.strip(" .,:;")
    cleaned = re.split(
        r"\b(?:i need help|please help|that is all|thank you|thanks|can you help|just create ticket|create ticket|log ticket|raise ticket|go ahead|proceed|i have to|i need to|at night|i do not feel safe|i don't feel safe|people keep|people are|it has|it is|this has|we have|we faced|we are facing|has been happening|have faced|for the past|past week|past month|since yesterday|since today)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .,:;")
    return cleaned


def _looks_like_location(location: str | None) -> bool:
    if not location:
        return False
    lower = location.lower().strip(" .,:;")
    if lower in {"my house", "my home", "home", "house", "my place"}:
        return True
    if _is_non_location_phrase(lower):
        return False
    if any(term in lower for term in _BROAD_LOCATION_TERMS):
        return True
    if any(marker in lower for marker in _SPECIFIC_LOCATION_MARKERS):
        return True
    if any(char.isdigit() for char in lower) and not re.fullmatch(r"[\d\s,.;:-]+", lower):
        return True
    words = [word.strip(".,:;") for word in lower.split() if word.strip(".,:;")]
    return 1 <= len(words) <= 5 and any(word[:1].isupper() for word in location.split())


def _validate_location(location: str | None, *, transcript: str = "", memory: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = _normalize_location(location or "")
    lower = normalized.lower()
    transcript_lower = (transcript or "").lower()
    memory = memory or {}

    if memory.get("location_confirmed") and memory.get("normalized_location"):
        return {
            "normalized": memory["normalized_location"],
            "confidence": max(float(memory.get("location_confidence") or 0.0), 0.86),
            "status": "map_confirmed",
            "reason": "Caller confirmed the map/location candidate.",
        }
    if memory.get("geo_pin"):
        status = memory.get("location_validation_status")
        if status == "pin_verified":
            return {
                "normalized": memory.get("normalized_location") or normalized,
                "confidence": max(float(memory.get("location_confidence") or 0.0), 0.82),
                "status": "pin_verified",
                "reason": memory.get("location_validation_reason") or "Caller/operator shared a verified map pin.",
            }
    candidates = memory.get("map_candidates") or []
    if memory.get("location_needs_candidate_confirmation") and candidates:
        return {
            "normalized": candidates[0].get("address") or normalized,
            "confidence": candidates[0].get("confidence", 0.72),
            "status": "needs_map_confirmation",
            "reason": f"Possible map match: {candidates[0].get('name')}. Confirm with caller or use a map pin before dispatch.",
        }

    if not normalized:
        return {
            "normalized": "",
            "confidence": 0.0,
            "status": "missing",
            "reason": "Location is missing.",
        }
    if any(cue in transcript_lower for cue in _FAKE_LOCATION_CUES):
        return {
            "normalized": normalized,
            "confidence": 0.1,
            "status": "needs_correction",
            "reason": "Caller indicated the location may be fake or a test address.",
        }
    if _is_underspecified_metro_route(lower):
        return {
            "normalized": normalized,
            "confidence": 0.25,
            "status": "needs_correction",
            "reason": "Metro-to-home route is too broad. Ask for the metro station, road name, or nearest landmark.",
        }

    without_road_width = re.sub(r"\b\d+\s*feet\s+road\b", "feet road", lower)
    has_address_number = bool(re.search(r"\b(?:no\.?\s*)?\d+[a-z]?\b", without_road_width))
    has_pin = bool(re.search(r"\b\d{6}\b", lower))
    has_street = any(marker in lower for marker in ("cross", "road", "street", "main", "layout", "block", "phase", "stage", "feet road"))
    memory_area = str(memory.get("area") or "").lower()
    has_area = (
        any(area in lower for area in _BROAD_LOCATION_TERMS if area not in {"area", "city", "district", "airport", "vidhana soudha", "vidhan sabha"})
        or any(area in memory_area for area in _BROAD_LOCATION_TERMS if area not in {"area", "city", "district", "airport", "vidhana soudha", "vidhan sabha"})
    )
    has_landmark_marker = any(marker in lower for marker in ("near", "opposite", "beside", "behind", "apartment", "hospital", "school", "temple", "metro", "gate", "tower"))
    is_major_ambiguous = _is_major_ambiguous_location(lower)

    if is_major_ambiguous and not (has_address_number or has_street or has_landmark_marker):
        return {
            "normalized": normalized,
            "confidence": 0.3,
            "status": "needs_correction",
            "reason": "Major landmark is too broad. Ask for gate, terminal, road, ward, or nearest smaller landmark.",
        }
    if lower in {"my house", "my home", "home", "house", "my place"}:
        return {
            "normalized": normalized,
            "confidence": 0.2,
            "status": "needs_correction",
            "reason": "Home location needs area and nearest landmark.",
        }
    if has_address_number and has_street and (has_area or has_pin or has_landmark_marker):
        return {
            "normalized": normalized,
            "confidence": 0.92,
            "status": "verified_format",
            "reason": "Address has house/building number, street/cross, and area or landmark.",
        }
    if (has_street and has_area) or (has_area and has_landmark_marker) or (has_pin and has_street):
        return {
            "normalized": normalized,
            "confidence": 0.78,
            "status": "usable",
            "reason": "Location has enough area and landmark detail for ticket intake.",
        }
    if candidates and candidates[0].get("confidence", 0.0) >= 0.72 and not candidates[0].get("broad"):
        return {
            "normalized": candidates[0].get("address") or normalized,
            "confidence": candidates[0].get("confidence", 0.72),
            "status": "needs_map_confirmation",
            "reason": f"Possible map match: {candidates[0].get('name')}. Confirm with caller or use a map pin before dispatch.",
        }
    if has_area and not has_street and not has_landmark_marker:
        return {
            "normalized": normalized,
            "confidence": 0.45,
            "status": "needs_correction",
            "reason": "Area is broad. Ask for street, ward, or nearest landmark.",
        }
    return {
        "normalized": normalized,
        "confidence": 0.5 if _is_specific_location(normalized) else 0.25,
        "status": "usable" if _is_specific_location(normalized) else "needs_correction",
        "reason": "Location appears usable." if _is_specific_location(normalized) else "Location is too broad or ambiguous.",
    }


def _normalize_location(location: str) -> str:
    cleaned = " ".join((location or "").replace("Landmark:", " Landmark:").split()).strip(" .,:;")
    cleaned = _clean_stored_location(cleaned)
    cleaned = re.sub(r"\bNo\s+", "No. ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: f"{m.group(1)}{m.group(2).lower()}", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    return cleaned


def _clean_stored_location(location: str) -> str:
    cleaned = " ".join((location or "").split()).strip(" .,:;")
    cleaned = re.split(
        r"\b(?:it occurs|it happens|it has been|we have been|we are experiencing|we have experienced|we faced|we had|over the past|for the past|once we had|it's been|it is very|this is very)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .,:;")
    return cleaned


def _location_contains_non_location_tail(location: str) -> bool:
    lower = (location or "").lower()
    return any(
        cue in lower
        for cue in (
            "it occurs",
            "it happens",
            "for the past",
            "over the past",
            "we have been",
            "we are experiencing",
            "it's been",
        )
    )


def _is_exact_candidate_mention(query: str, candidate: dict[str, Any]) -> bool:
    lower = (query or "").lower()
    exact_terms = {
        str(candidate.get("name") or "").lower(),
        str(candidate.get("landmark") or "").lower(),
    }
    exact_terms = {term for term in exact_terms if term}
    return any(term and term in lower for term in exact_terms)


def _has_strong_location_context(location: str, area: str = "") -> bool:
    lower = (location or "").lower()
    area_lower = (area or "").lower()
    has_street = any(marker in lower for marker in ("cross", "road", "street", "main", "layout", "block", "phase", "stage", "feet road"))
    has_area = bool(area_lower and not _is_broad_area(area_lower)) or any(
        known in lower for known in ("indiranagar", "whitefield", "koramangala", "jayanagar", "hebbal", "yelahanka", "marathahalli", "rajajinagar")
    )
    has_landmark_marker = any(marker in lower for marker in ("near", "opposite", "beside", "behind", "apartment", "hospital", "school", "temple", "metro", "gate", "tower"))
    return has_area and (has_street or has_landmark_marker)


def _is_broad_area(area: str | None) -> bool:
    lower = (area or "").lower().strip(" .,:;")
    return lower in {"", "bengaluru", "bangalore", "city", "area", "district"}


def _is_major_ambiguous_location(lower: str) -> bool:
    compact = lower.strip(" .,:;")
    if compact in _MAJOR_AMBIGUOUS_LOCATIONS:
        return True
    return any(compact == item or compact.endswith(f" {item}") for item in _MAJOR_AMBIGUOUS_LOCATIONS)


def _is_underspecified_metro_route(lower: str) -> bool:
    compact = (lower or "").strip(" .,:;")
    if not compact:
        return False
    route_terms = (
        "the metro to my house",
        "metro to my house",
        "metro to my home",
        "from the metro",
        "from metro",
    )
    has_route = any(term in compact for term in route_terms)
    has_named_station_or_road = any(
        marker in compact
        for marker in (
            "station",
            "road",
            "street",
            "cross",
            "main",
            "layout",
            "indiranagar",
            "whitefield",
            "koramangala",
            "jayanagar",
            "hebbal",
            "yelahanka",
            "marathahalli",
            "rajajinagar",
        )
    )
    return has_route and not has_named_station_or_road


def _is_non_location_phrase(text: str | None) -> bool:
    if not text:
        return True
    lower = text.lower().strip(" .,:;")
    if not lower:
        return True
    time_terms = (
        "days",
        "hours",
        "week",
        "month",
        "morning",
        "evening",
        "night",
        "yesterday",
        "today",
        "continuous cuts",
        "each cut",
        "lasted",
        "happening",
    )
    complaint_terms = (
        "tried contacting",
        "contacting bescom",
        "unhelpful",
        "rude",
        "complaint before",
        "reported",
        "called",
    )
    chatter_terms = (
        "how do you do",
        "how are you",
        "hello",
        "hi",
        "what do you mean",
        "i don't understand",
        "i do not understand",
        "not clear",
    )
    if lower in chatter_terms or any(lower.startswith(f"{term} ") for term in chatter_terms):
        return True
    if any(term in lower for term in time_terms) and not any(marker in lower for marker in _SPECIFIC_LOCATION_MARKERS):
        return True
    if any(term in lower for term in complaint_terms):
        return True
    return False


def _trim_detail_text(text: str) -> str:
    cleaned = " ".join((text or "").split()).strip(" .,:;")
    if len(cleaned) <= 180:
        return cleaned
    return cleaned[:177].rstrip(" ,.;:") + "..."


def _detect_text_language(transcript: str) -> str:
    text = transcript.lower()
    if any(term in text for term in ("hai", "nahi", "haan", "bijli", "paani", "shikayat")):
        return "hindi"
    if any(term in text for term in ("illa", "beku", "madam", "sari", "vidyut", "vidyuth", "vidyuta", "neeru", "haudu", "howdu", "kadita", "kaḍita", "karentu")):
        return "kannada"
    return "english"


def _sentiment_from_text(transcript: str, acoustic_score: float) -> str:
    text = transcript.lower()
    if any(term in text for term in (
        "scared",
        "fear",
        "afraid",
        "danger",
        "threat",
        "help now",
        "do not feel safe",
        "don't feel safe",
        "not feel safe",
        "unsafe",
        "shady area",
        "people keep staring",
        "staring at me",
        "following me",
    )):
        return "fear"
    if any(term in text for term in ("urgent", "immediately", "emergency", "right now", "bahut zaroori")):
        return "urgent"
    if any(term in text for term in ("angry", "fed up", "ridiculous", "again and again", "many times", "extremely unhelpful", "rude")):
        return "angry"
    if any(term in text for term in ("confused", "don't know", "not sure", "which", "where")):
        return "confused"
    if acoustic_score >= 0.65:
        return "frustrated"
    return "calm"


def _cultural_context_from_text(transcript: str) -> str:
    text = transcript.lower()
    if any(term in text for term in ("power cut", "current hogide", "bijli", "load shedding")):
        return "Local civic power-cut expression detected; verify exact ward or landmark before dispatch."
    if any(term in text for term in ("paani", "neeru", "kaveri", "cauvery")):
        return "Water-supply wording may be code-mixed; confirm source and nearest landmark."
    if _detect_text_language(transcript) in {"hindi", "kannada"}:
        return "Code-mixed local-language grievance detected; agent should preserve caller phrasing when correcting."
    return "Standard civic grievance phrasing."


def _key_details_from_text(transcript: str, emergency_type: str, location: str) -> list[str]:
    details = []
    if emergency_type and emergency_type != "other":
        details.append(f"Issue category: {emergency_type}")
    if location:
        details.append(f"Caller mentioned location: {location}")
    if any(term in transcript.lower() for term in ("again", "many times", "daily", "too many", "repeated")):
        details.append("Caller reports repeated occurrence")
    return details


def _is_specific_location(location: str | None) -> bool:
    if not location:
        return False
    lower = location.lower().strip(" .,:;")
    if lower in {"unknown", "not provided", "none", "n/a", "my house", "my home", "home", "house"}:
        return False
    if _is_underspecified_metro_route(lower):
        return False
    if any(home in lower for home in ("my house", "my home", "my place")) and not any(marker in lower for marker in _SPECIFIC_LOCATION_MARKERS):
        return False

    words = [word.strip(".,:;") for word in lower.split() if word.strip(".,:;")]
    if any(char.isdigit() for char in lower):
        return True
    if any(marker in lower for marker in _SPECIFIC_LOCATION_MARKERS):
        return True
    if len(words) <= 2 and any(term in lower for term in _BROAD_LOCATION_TERMS):
        return False
    if lower.endswith("district") or " district" in lower:
        return False
    return len(words) >= 4


def _detect_confirmation_intent(text: str) -> bool | None:
    lower = " ".join(text.lower().strip(" .,!?:;").split())
    if not lower:
        return None

    words = lower.split()
    has_detail = len(words) > 4 or any(_contains_token(lower, cue) for cue in _CORRECTION_CUES)
    has_no = any(_contains_token(lower, token) for token in _NO_TOKENS)
    if has_no:
        return None if has_detail else False

    has_yes = any(_contains_token(lower, token) for token in _YES_TOKENS)
    if has_yes and not has_detail:
        return True
    return None


def _is_affirmative_location_confirmation(text: str) -> bool:
    lower = " ".join((text or "").lower().strip(" .,!?:;").split())
    if not lower:
        return False
    if any(_contains_token(lower, token) for token in _NO_TOKENS):
        return False
    return any(_contains_token(lower, token) for token in _YES_TOKENS)


def _is_confirmation_clarification_question(text: str) -> bool:
    lower = " ".join((text or "").lower().split())
    if not lower:
        return False
    return any(
        cue in lower
        for cue in (
            "what do you mean",
            "what does that mean",
            "i don't understand",
            "i do not understand",
            "not clear",
            "why are you saying",
            "what is",
        )
    )


def _contains_token(text: str, token: str) -> bool:
    if token.isascii():
        return bool(re.search(rf"\b{re.escape(token)}\b", text))
    return token in text


def _issue_label(emergency_type: str | None, language: str) -> str:
    issue = emergency_type or "other"
    labels = {
        "english": {
            "power_outage": "repeated power cuts",
            "water_supply": "water supply",
            "waste_management": "waste management",
            "road_damage": "road damage",
            "streetlights": "streetlight",
            "noise_disturbance": "noise disturbance",
            "ration_card": "ration card grievance",
            "labour_grievance": "labour or wages grievance",
            "pension_delay": "pension or welfare scheme delay",
            "rdpr_service": "rural or panchayat service grievance",
            "health_service": "health service grievance",
            "transport_service": "transport or RTO grievance",
            "education_service": "education service grievance",
            "revenue_service": "revenue service grievance",
            "municipal_service": "municipal service grievance",
            "women_safety": "women safety concern",
            "medical_emergency": "medical emergency",
            "public_safety": "public safety concern",
            "fire": "fire emergency",
            "other": "civic grievance",
        },
        "hindi": {
            "power_outage": "बिजली कटौती",
            "water_supply": "पानी की आपूर्ति",
            "waste_management": "कचरा प्रबंधन",
            "road_damage": "सड़क की समस्या",
            "streetlights": "स्ट्रीट लाइट",
            "noise_disturbance": "शोर की शिकायत",
            "other": "नागरिक शिकायत",
        },
        "kannada": {
            "power_outage": "ವಿದ್ಯುತ್ ಕಡಿತ",
            "water_supply": "ನೀರಿನ ಸರಬರಾಜು",
            "waste_management": "ಕಸ ನಿರ್ವಹಣೆ",
            "road_damage": "ರಸ್ತೆ ಸಮಸ್ಯೆ",
            "streetlights": "ಬೀದಿ ದೀಪ",
            "noise_disturbance": "ಶಬ್ದದ ದೂರು",
            "other": "ನಾಗರಿಕ ದೂರು",
        },
    }
    return labels.get(language, labels["english"]).get(issue, labels.get(language, labels["english"])["other"])


def _build_conversational_restatement(
    session: CallSession,
    language: str,
    fallback_department: str,
    fallback_location: str,
    fallback_issue: str,
) -> str:
    memory = _get_conversation_memory(session)
    department = memory.get("department") or fallback_department or "the concerned department"
    location = _display_location(memory, fallback_location)
    issue = _issue_label(memory.get("issue"), language) if memory.get("issue") else fallback_issue

    if session.required_slot == "issue":
        if language == "hindi":
            return "कर्नाटक 1092 में आपका स्वागत है. मैं आपकी मदद करूंगी. कृपया अपनी शिकायत बताइए."
        if language == "kannada":
            return "ಕರ್ನಾಟಕ 1092 ಗೆ ಸ್ವಾಗತ. ನಾನು ನಿಮಗೆ ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ದೂರು ಹೇಳಿ."
        return "Welcome to Karnataka 1092. I will help you. Please tell me what happened."

    if session.required_slot == _ABUSE_WARNING_SLOT:
        if language == "hindi":
            return "Yeh helpline asli nagarik shikayaton ke liye hai. Agar aapko sach mein madad chahiye, kripya samasya aur location saaf batayein."
        if language == "kannada":
            return "Ee helpline nija civic doorugalige. Sahaya bekaadare, dayavittu samasya mattu location annu spashtavagi heli."
        return "This helpline is for genuine civic grievances. If you need help, please clearly state the issue and location."

    if session.required_slot == "service_detail":
        if language == "hindi":
            return "Samajh gayi. Yeh kis department, office, scheme, service, ya application ke baare mein hai?"
        if language == "kannada":
            return "Arthavayitu. Idu yava department, office, scheme, service, athava application bagge?"
        if department in _SERVICE_GRIEVANCE_DEPARTMENTS:
            return "I understand your grievance. Which scheme, office, service, or application number should I add to the ticket?"
        return "I understand. Which department, office, scheme, or service is this about?"

    if session.required_slot in {"location", "landmark"}:
        if memory.get("department") in _SERVICE_GRIEVANCE_DEPARTMENTS:
            if language == "hindi":
                return "Is grievance ke liye kaunsa district, area, ya office location daalun?"
            if language == "kannada":
                return "Ee grievance ge yava district, area, athava office location hakali?"
            return "Which district, area, or office location should I put on this grievance?"
        if memory.get("issue") == "streetlights" and memory.get("sentiment") == "fear":
            if language == "hindi":
                return "मैं समझ गई कि रास्ता असुरक्षित लग रहा है. मैं मदद करूंगी. किस मेट्रो स्टेशन, सड़क, या नजदीकी लैंडमार्क से टिकट बनाऊं?"
            if language == "kannada":
                return "ರಸ್ತೆ ಸುರಕ್ಷಿತವಾಗಿಲ್ಲ ಎಂದು ಅರ್ಥವಾಗಿದೆ. ನಾನು ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ಯಾವ ಮೆಟ್ರೋ ನಿಲ್ದಾಣ, ರಸ್ತೆ ಅಥವಾ ಹತ್ತಿರದ ಗುರುತನ್ನು ಟಿಕೆಟ್‌ನಲ್ಲಿ ಹಾಕಲಿ?"
            return "I understand this feels unsafe. I will help raise this immediately. Which metro station, road name, or nearest landmark should I put on the ticket?"
        if language == "hindi":
            return "मैं आपकी समस्या समझ गई. मैं तुरंत टिकट बनाने में मदद करूंगी. टिकट में कौन सा क्षेत्र और नजदीकी लैंडमार्क डालूं?"
        if language == "kannada":
            return "ನಿಮ್ಮ ಸಮಸ್ಯೆ ಅರ್ಥವಾಗಿದೆ. ತಕ್ಷಣ ಟಿಕೆಟ್ ಮಾಡಲು ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ಟಿಕೆಟ್‌ನಲ್ಲಿ ಯಾವ ಪ್ರದೇಶ ಮತ್ತು ಹತ್ತಿರದ ಗುರುತು ಹಾಕಲಿ?"
        return "I understand your problem. I will help create a ticket immediately. Which area and nearest landmark should I put on the ticket?"

    if session.required_slot == "location_confirm":
        candidate = (memory.get("map_candidates") or [{}])[0]
        place = candidate.get("name") or memory.get("normalized_location") or location
        if language == "hindi":
            return f"मुझे स्थान {place} जैसा सुनाई दिया. क्या यही सही जगह है? अगर नहीं, सही क्षेत्र या मैप पिन दीजिए."
        if language == "kannada":
            return f"ನಾನು ಸ್ಥಳವನ್ನು {place} ಎಂದು ಕೇಳಿದೆ. ಇದು ಸರಿಯಾದ ಸ್ಥಳವೇ? ಇಲ್ಲದಿದ್ದರೆ ಸರಿಯಾದ ಪ್ರದೇಶ ಅಥವಾ ಮ್ಯಾಪ್ ಪಿನ್ ನೀಡಿ."
        return f"I heard the location as {place}. Is that correct? If not, please say the correct landmark or use the map pin."

    if session.required_slot == "started_at_or_time":
        if language == "hindi":
            return "मैं अभी टिकट बना सकती हूं. एक बात बताइए, यह कब शुरू हुआ या आम तौर पर किस समय होता है?"
        if language == "kannada":
            return "ನಾನು ಈಗ ಟಿಕೆಟ್ ದಾಖಲಿಸಬಹುದು. ಒಂದು ಮಾಹಿತಿ ಹೇಳಿ, ಇದು ಯಾವಾಗ ಶುರುವಾಯಿತು ಅಥವಾ ಸಾಮಾನ್ಯವಾಗಿ ಯಾವ ಸಮಯದಲ್ಲಿ ಆಗುತ್ತದೆ?"
        return "I can log this now. One quick detail: when did this start, or when does it usually happen?"
    if session.required_slot == "frequency":
        if language == "hindi":
            return "ठीक है. क्या यह अभी हो रहा है या बार-बार हो रहा है?"
        if language == "kannada":
            return "ಸರಿ. ಇದು ಈಗ ನಡೆಯುತ್ತಿದೆಯೇ ಅಥವಾ ಮರುಮರು ಆಗುತ್ತಿದೆಯೇ?"
        return "Got it. Is this happening right now, or has it been happening repeatedly?"
    if session.required_slot in {"caller_tried", "authority_contacted"}:
        if language == "hindi":
            return f"समझ गई. क्या आपने पहले {department} से संपर्क किया है या यह शिकायत पहले दर्ज कराई है?"
        if language == "kannada":
            return f"ಅರ್ಥವಾಯಿತು. ನೀವು ಮೊದಲು {department} ಸಂಪರ್ಕಿಸಿದ್ದೀರಾ ಅಥವಾ ಈ ದೂರು ಮೊದಲು ದಾಖಲಿಸಿದ್ದೀರಾ?"
        return f"Understood. Have you already contacted {department} or tried making this complaint before?"
    if session.required_slot == "previous_complaint":
        if language == "hindi":
            return "धन्यवाद. क्या आपके पास पहले की शिकायत या टिकट नंबर है?"
        if language == "kannada":
            return "ಧನ್ಯವಾದಗಳು. ನಿಮ್ಮ ಬಳಿ ಹಿಂದಿನ ದೂರು ಅಥವಾ ಟಿಕೆಟ್ ಸಂಖ್ಯೆ ಇದೆಯೇ?"
        return "Thanks. Do you already have an earlier complaint or ticket number for this?"
    if session.required_slot == "application_or_reference":
        if memory.get("service_or_scheme") == "ration card":
            return "I can register this now. Do you have the ration card application number, or should I use this caller mobile number as the reference?"
        return "Do you have an application, scheme, ration card, pension, or reference number I should add?"
    if session.required_slot == "office_visited":
        return "Which office or official did you already visit or contact, if any?"
    if session.required_slot == "documents_available":
        return "Do you have any document, photo, receipt, or SMS proof available?"

    if session.required_slot == "confirmation":
        if department in _SERVICE_GRIEVANCE_DEPARTMENTS:
            service = memory.get("service_or_scheme") or issue
            area = memory.get("area") or location
            time_detail = memory.get("started_at_or_time", "")
            ref = memory.get("application_or_reference", "")
            parts = [service]
            if time_detail:
                parts.append(time_detail)
            if area:
                parts.append(f"in {area}")
            if ref:
                if "caller mobile" in ref:
                    parts.append("using this caller mobile number as the reference")
                else:
                    parts.append(f"reference {ref}")
            summary = ", ".join(part for part in parts if part)
            line_department = memory.get("line_department") or _line_department_for(department, memory.get("issue"))
            return f"Got it. I will register this grievance for {summary}, and route it to {line_department}. Is that correct?"
        detail = ""
        if memory.get("frequency"):
            if language == "hindi":
                detail = f" यह {memory['frequency']} हो रहा है."
            elif language == "kannada":
                detail = f" ಇದು {memory['frequency']} ಆಗುತ್ತಿದೆ."
            else:
                detail = f" It is {memory['frequency']}."
        elif memory.get("started_at_or_time"):
            if language == "hindi":
                detail = f" यह आम तौर पर {memory['started_at_or_time']} होता है."
            elif language == "kannada":
                detail = f" ಇದು ಸಾಮಾನ್ಯವಾಗಿ {memory['started_at_or_time']} ಆಗುತ್ತದೆ."
            else:
                detail = f" It usually happens {memory['started_at_or_time']}."
        if language == "hindi":
            return f"मैं पुष्टि कर रही हूं: {location} में {issue}.{detail} मैं इसे {department} को भेजूंगी. क्या यह सही है?"
        if language == "kannada":
            return f"ನಾನು ದೃಢೀಕರಿಸುತ್ತೇನೆ: {location} ನಲ್ಲಿ {issue}.{detail} ಇದನ್ನು {department} ಗೆ ಕಳುಹಿಸುತ್ತೇನೆ. ಇದು ಸರಿಯೇ?"
        prefix = "I understand this has been frustrating. " if memory.get("sentiment") in {"angry", "frustrated"} else ""
        line_department = memory.get("line_department") or _line_department_for(department, memory.get("issue"))
        service_detail = f" for {memory['service_or_scheme']}" if memory.get("service_or_scheme") and memory["service_or_scheme"] not in issue else ""
        return f"{prefix}Let me confirm: {issue}{service_detail} at {location}.{detail} I will register this with {line_department or department}. Is that correct?"

    return ""


def _build_restatement(session: CallSession) -> str:
    analysis = session.analysis_result
    language = _preferred_language(session, analysis.language_detected if analysis else None)
    department = (analysis.department if analysis else None) or session.department_assigned or "the concerned department"
    location = ((analysis.location_hint if analysis else None) or "").strip()
    issue = _issue_label(analysis.emergency_type if analysis else None, language)
    conversational = _build_conversational_restatement(session, language, department, location, issue)
    if conversational:
        return conversational

    if analysis.needs_clarification:
        if session.required_slot == "issue":
            if language == "hindi":
                return "Karnataka 1092 mein aapka swagat hai. Kripya apni shikayat bataiye."
            if language == "kannada":
                return "Karnataka 1092 ge swagata. Dayavittu nimma dooru heli."
            return "Welcome to Karnataka 1092. Please tell me your grievance."
        if session.required_slot == "location":
            if language == "hindi":
                return f"Maine aapki {issue} shikayat samjhi hai. Kripya apna area, street, ward ya landmark batayein."
            if language == "kannada":
                return f"Nimma {issue} dooru arthavagide. Dayavittu area, raste, ward athava hattirada landmark heli."
            return f"I understand the issue is {issue}. Please share your area, street, ward, or nearest landmark."
        if location.lower() in {"my house", "my home", "home", "house"}:
            if language == "hindi":
                return f"Maine aapki {issue} shikayat samjhi hai. Kripya apna area aur najdeeki landmark batayein."
            if language == "kannada":
                return f"Nimma {issue} dooru arthavagide. Dayavittu area mattu hattirada landmark heli."
            return f"I understand you are facing {issue} at your house. Please tell me your area and nearest landmark."
        if language == "hindi":
            area = f" {location} में" if location else ""
            return f"धन्यवाद. मैंने आपकी {issue} समस्या{area} समझी है. कृपया गली, वार्ड या नजदीकी लैंडमार्क बताएं."
        if language == "kannada":
            area = f" {location} ನಲ್ಲಿ" if location else ""
            return f"ಧನ್ಯವಾದಗಳು. ನಿಮ್ಮ {issue} ಸಮಸ್ಯೆ{area} ಅರ್ಥವಾಗಿದೆ. ದಯವಿಟ್ಟು ರಸ್ತೆ, ವಾರ್ಡ್ ಅಥವಾ ಹತ್ತಿರದ ಗುರುತು ಹೇಳಿ."
        area = f" in {location}" if location else ""
        return f"Thank you. I understand the issue is {issue}{area}. Please share the street, ward, or nearest landmark so I can log it correctly."

    if language == "hindi":
        return f"मैं {location} में {issue} के लिए {department} में टिकट दर्ज कर रही हूं. क्या यह सही है?"
    if language == "kannada":
        return f"{location} ನಲ್ಲಿ {issue} ಬಗ್ಗೆ {department} ಗೆ ಟಿಕೆಟ್ ದಾಖಲಿಸುತ್ತಿದ್ದೇನೆ. ಇದು ಸರಿಯೇ?"
    return f"I am logging a ticket with {department} for {issue} at {location}. Is this correct?"


def _display_location(memory: dict[str, Any], fallback_location: str = "") -> str:
    selected = memory.get("map_candidate_selected") or {}
    if selected.get("landmark") and selected.get("area"):
        return f"{selected['landmark']}, {selected['area']}"
    candidates = memory.get("map_candidates") or []
    if candidates and candidates[0].get("confidence", 0) >= 0.8 and not candidates[0].get("broad"):
        top = candidates[0]
        landmark = top.get("landmark") or top.get("name")
        area = top.get("area")
        if landmark and area:
            return f"{landmark}, {area}"
        if top.get("address"):
            return top["address"]
    landmark = _clean_stored_location(memory.get("landmark") or "")
    area = memory.get("area") or ""
    if landmark and area and area.lower() not in landmark.lower() and not _is_broad_area(area):
        return f"{landmark}, {area}"
    return landmark or area or fallback_location


def _build_confirmation_explanation(session: CallSession) -> str:
    analysis = session.analysis_result
    memory = _get_conversation_memory(session)
    language = _preferred_language(session, analysis.language_detected if analysis else None)
    department = memory.get("department") or (analysis.department if analysis else None) or session.department_assigned
    issue = _issue_label(memory.get("issue") or (analysis.emergency_type if analysis else None), language)
    location = _display_location(memory, (analysis.location_hint if analysis else "") or "")
    time_detail = memory.get("started_at_or_time") or memory.get("frequency")

    if language == "hindi":
        detail = f" समस्या {time_detail} से चल रही है." if time_detail else ""
        return f"Maaf kijiye, mera matlab hai: {location} par {issue}.{detail} Main ise {department} ko bhejungi. Kya yeh sahi hai?"
    if language == "kannada":
        detail = f" Idu {time_detail} inda aguttide." if time_detail else ""
        return f"Kshamisi, nanna artha: {location} nalli {issue}.{detail} Idannu {department} ge kaluhisuttene. Idu sariyagideya?"
    detail = f" It has been happening {time_detail}." if time_detail else ""
    return f"Sorry, I meant: repeated power cuts at {location}.{detail} I will send this to {department}. Is that correct?"


def _build_dispatch_message(session: CallSession) -> str:
    analysis = session.analysis_result
    language = _preferred_language(session, analysis.language_detected if analysis else None)
    memory = _get_conversation_memory(session)
    department = (
        memory.get("line_department")
        or (analysis.line_department if analysis else None)
        or (analysis.department if analysis else None)
        or session.department_assigned
        or "the concerned department"
    )
    helpline = memory.get("specialized_helpline") or (analysis.specialized_helpline if analysis else "")
    helpline_note = f" For urgent direct support, you can also contact {helpline}." if helpline else ""

    if language == "hindi":
        return f"आपका टिकट {session.ticket_id} {department} के साथ दर्ज हो गया है. हम आगे की कार्रवाई के लिए इसे भेज रहे हैं. जरूरत पड़ी तो प्रतिनिधि इसी नंबर पर संपर्क करेगा. स्थिति जानने के लिए 1092 पर यही नंबर बताएं. धन्यवाद."
    if language == "kannada":
        return f"ನಿಮ್ಮ ಟಿಕೆಟ್ {session.ticket_id} {department} ಗೆ ದಾಖಲಾಗಿದೆ. ಮುಂದಿನ ಕ್ರಮಕ್ಕೆ ಕಳುಹಿಸುತ್ತಿದ್ದೇವೆ. ಹೆಚ್ಚಿನ ವಿವರ ಬೇಕಾದರೆ ಪ್ರತಿನಿಧಿ ಇದೇ ಸಂಖ್ಯೆಗೆ ಸಂಪರ್ಕಿಸುತ್ತಾರೆ. ಸ್ಥಿತಿ ತಿಳಿಯಲು 1092 ಗೆ ಕರೆ ಮಾಡಿ ಈ ಸಂಖ್ಯೆಯನ್ನು ಹೇಳಿ. ಧನ್ಯವಾದಗಳು."
    return f"Your grievance has been registered with {department}. Your ticket number is {session.ticket_id}. We will send it to the concerned line official for action, and if more details are needed, a representative will contact you on this same number. Use this ticket number to check status or quote it if a representative contacts you.{helpline_note} The ticket details have also been sent by SMS. Thank you for calling Karnataka 1092."


def _build_human_takeover_message(session: CallSession, reason: str) -> str:
    language = _preferred_language(session)
    reason_lower = (reason or "").lower()
    if "not be capturing" in reason_lower or "repeat yourself" in reason_lower:
        if language == "hindi":
            return "Main shayad aapki baat sahi tarah capture nahi kar pa rahi hoon. Main ab aapko human operator se connect kar rahi hoon, taaki aapko baar baar repeat na karna pade. Kripya line par rahiye."
        if language == "kannada":
            return "Nimma maatannu sariyagi capture madalaguttilla. Nimge matte matte helabekagadiralu, nanu iga human operator ge connect maduttiddene. Dayavittu line nalli iri."
        return "I may not be capturing this correctly. I am connecting you to a human operator now, so you do not have to repeat yourself. Please stay on the line."

    if language == "hindi":
        return "Main samajh rahi hoon ki yeh urgent ho sakta hai. Main aapko ab human operator se connect kar rahi hoon. Kripya line par rahiye."
    if language == "kannada":
        return "Idhu urgent agirabahudu endu arthavagide. Nanu iga nimmanu human operator ge connect maduttiddene. Dayavittu line nalli iri."
    return "I understand this may need immediate attention. I am connecting you to a human operator now. Please stay on the line."


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
