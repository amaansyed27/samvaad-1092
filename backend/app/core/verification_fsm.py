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

_REQUIRED_CLARIFICATION_SLOTS = {"issue", "location", "landmark", "correction"}
_OPTIONAL_DETAIL_SLOTS = (
    "started_at_or_time",
    "frequency",
    "caller_tried",
    "authority_contacted",
    "previous_complaint",
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
            session.raw_transcript += " " + transcript.strip()
            self._transition(session, VerificationState.SCRUB)
            return {
                "event": "state_change",
                "state": "SCRUB",
                "note": "Caller supplied correction or extra details",
            }

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
        if session.analysis_result.needs_clarification and is_required_clarification and session.clarification_count >= 2:
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

    if emergency_type and emergency_type != "other":
        memory["issue"] = emergency_type
    if department and department not in {"UNASSIGNED", "UNKNOWN", "OTHER"}:
        memory["department"] = department

    location = _extract_location_hint(text)
    if location:
        if _is_specific_location(location):
            memory["landmark"] = location
            memory["area"] = _area_from_location(location) or _area_from_location(text) or memory.get("area", "")
        elif location.lower().strip(" .,:;") not in {"my house", "my home", "home", "house"}:
            memory["area"] = location
    else:
        location_phrase = _extract_standalone_location(text)
        if location_phrase:
            if _is_specific_location(location_phrase):
                memory["landmark"] = location_phrase
                memory["area"] = _area_from_location(location_phrase) or memory.get("area", "")
            else:
                memory["area"] = location_phrase

    memory["sentiment"] = sentiment
    memory["urgency"] = "HIGH" if sentiment in {"angry", "fear", "urgent", "frustrated"} else "LOW"

    if any(cue in lower for cue in _SKIP_OPTIONAL_CUES):
        memory["skip_optional"] = True
    if any(term in lower for term in ("right now", "currently", "now", "happening now")):
        memory["currently_happening"] = "yes"
    if any(term in lower for term in ("every night", "daily", "again and again", "many times", "repeated", "too many")):
        memory["frequency"] = _extract_frequency(text)
    if any(term in lower for term in ("since", "morning", "evening", "night", "yesterday", "today", "week", "month")):
        memory["started_at_or_time"] = _extract_time_detail(text)
    if any(term in lower for term in ("tried", "checked", "called", "reported", "complained", "complaint")):
        memory["caller_tried"] = text
    authority = _extract_authority_contact(lower)
    if authority:
        memory["authority_contacted"] = authority
    previous = _extract_previous_complaint(text)
    if previous:
        memory["previous_complaint"] = previous

    usable_location = bool(memory.get("landmark")) or _is_specific_location(memory.get("area"))
    memory["ticket_ready"] = bool(memory.get("issue") and memory.get("department") and usable_location)
    session.conversation_memory = memory
    return memory


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
    for slot in _OPTIONAL_DETAIL_SLOTS:
        if not memory.get(slot):
            return slot
    return ""


def _area_from_location(location: str) -> str:
    lower = location.lower()
    for area in _BROAD_LOCATION_TERMS:
        if area in lower:
            return area.title()
    return ""


def _extract_standalone_location(text: str) -> str:
    cleaned = text.strip(" .,:;")
    lower = cleaned.lower()
    if not cleaned or len(cleaned.split()) > 8:
        return ""
    location_terms = set(_BROAD_LOCATION_TERMS) | _SPECIFIC_LOCATION_MARKERS
    if any(term in lower for term in location_terms):
        return cleaned
    return ""


def _extract_time_detail(text: str) -> str:
    lower = text.lower()
    patterns = [
        r"since\s+[^,.]+",
        r"every\s+(?:morning|evening|night|day)",
        r"(?:morning|evening|night|yesterday|today|last\s+week|this\s+week)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return match.group(0).strip()
    return text.strip(" .,:;")


def _extract_frequency(text: str) -> str:
    lower = text.lower()
    if "every night" in lower:
        return "every night"
    if "daily" in lower:
        return "daily"
    if "again and again" in lower:
        return "again and again"
    if "many times" in lower or "too many" in lower or "repeated" in lower:
        return "repeated"
    return text.strip(" .,:;")


def _extract_authority_contact(lower: str) -> str:
    for authority in ("bescom", "bbmp", "bwssb", "police", "fire", "1092"):
        if authority in lower and any(term in lower for term in ("called", "contacted", "reported", "complained")):
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


def _build_fast_analysis(
    session: CallSession,
    transcript: str,
    acoustic_score: float,
) -> dict[str, Any]:
    """Deterministic call-centre analysis for the live demo path."""
    transcript = transcript or session.raw_transcript or ""
    deterministic_department = _infer_department(transcript)
    if deterministic_department != "OTHER":
        department = deterministic_department
    elif session.department_assigned and session.department_assigned not in {"UNASSIGNED", "UNKNOWN"}:
        department = session.department_assigned
    else:
        department = "OTHER"

    emergency_type = _infer_emergency_type(transcript, department)
    language = _preferred_language(session, _detect_text_language(transcript))
    sentiment = _sentiment_from_text(transcript, acoustic_score)
    has_issue = _has_issue_signal(transcript, department, emergency_type)
    memory = _update_conversation_memory(session, transcript, department, emergency_type, sentiment)
    location = memory.get("landmark") or memory.get("area") or _extract_location_hint(transcript)
    location_specific = bool(memory.get("landmark")) or _is_specific_location(location)
    needs_clarification = False
    key_details = _key_details_from_text(transcript, emergency_type, location)

    if not has_issue:
        session.required_slot = "issue"
        needs_clarification = True
        key_details.append("Needs grievance details")
    elif location.lower().strip(" .,:;") in {"my house", "my home", "home", "house"}:
        session.required_slot = "landmark"
        needs_clarification = True
        key_details.append("Needs area and nearest landmark for caller home")
    elif not memory.get("area") and not memory.get("landmark"):
        session.required_slot = "location"
        needs_clarification = True
        key_details.append("Needs caller location")
    elif not location_specific:
        session.required_slot = "landmark"
        needs_clarification = True
        key_details.append(f"Needs street, ward, or nearest landmark for {location}")
    elif _should_ask_optional_detail(session, memory):
        session.required_slot = _next_optional_slot(memory) or "confirmation"
        needs_clarification = session.required_slot != "confirmation"
    else:
        session.required_slot = "confirmation"

    memory["ticket_ready"] = bool(has_issue and department not in {"OTHER", "UNKNOWN", "UNASSIGNED"} and location_specific)
    memory["missing_slot"] = session.required_slot if needs_clarification else ""
    session.conversation_memory = memory

    semantic_distress = max(
        min(acoustic_score, 0.85),
        0.75 if sentiment in {"angry", "fear", "urgent"} else 0.35,
    )
    requires_takeover = acoustic_score >= 0.88 or sentiment == "fear"
    severity = "high" if semantic_distress >= 0.7 else "medium" if semantic_distress >= 0.45 else "low"
    priority = "HIGH" if severity == "high" else "MEDIUM" if severity == "medium" else "LOW"

    return {
        "emergency_type": emergency_type,
        "department": department,
        "location_hint": location,
        "severity": severity,
        "priority": priority,
        "sentiment": sentiment,
        "language_detected": language,
        "key_details": key_details,
        "cultural_context": _cultural_context_from_text(transcript),
        "semantic_distress_score": semantic_distress,
        "needs_clarification": needs_clarification,
        "requires_immediate_takeover": requires_takeover,
        "confidence": 0.74 if needs_clarification else 0.88,
    }


def _build_slot_view(session: CallSession) -> dict[str, Any]:
    analysis = session.analysis_result
    memory = _get_conversation_memory(session)
    location = memory.get("landmark") or memory.get("area") or ((analysis.location_hint if analysis else "") or "")
    slots = {
        "issue": memory.get("issue") or (analysis.emergency_type if analysis else ""),
        "department": memory.get("department") or (analysis.department if analysis else None) or session.department_assigned,
        "location": location,
        "area": memory.get("area", ""),
        "location_specific": bool(memory.get("landmark")) or _is_specific_location(location),
        "landmark": memory.get("landmark", ""),
        "started_at_or_time": memory.get("started_at_or_time", ""),
        "frequency": memory.get("frequency", ""),
        "currently_happening": memory.get("currently_happening", ""),
        "caller_tried": memory.get("caller_tried", ""),
        "authority_contacted": memory.get("authority_contacted", ""),
        "previous_complaint": memory.get("previous_complaint", ""),
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


def _infer_department(transcript: str) -> str:
    text = transcript.lower()
    if any(term in text for term in ("power", "electric", "electrical", "electricity", "current", "voltage", "transformer", "streetlight")):
        return "BESCOM"
    if any(term in text for term in ("water", "sewage", "drainage", "pipe", "cauvery")):
        return "BWSSB"
    if any(term in text for term in ("garbage", "pothole", "road", "waste", "tree", "drain")):
        return "BBMP"
    if any(term in text for term in ("fire", "smoke", "gas leak", "blast")):
        return "FIRE"
    if any(term in text for term in ("theft", "fight", "harassment", "following", "noise")):
        return "POLICE"
    return "OTHER"


def _infer_emergency_type(transcript: str, department: str) -> str:
    text = transcript.lower()
    if any(term in text for term in ("power", "electric", "electrical", "electricity", "current", "voltage", "transformer", "cut", "cuts")):
        return "power_outage"
    if "streetlight" in text:
        return "streetlights"
    if department == "BWSSB":
        return "water_supply"
    if department == "BBMP" and "road" in text:
        return "road_damage"
    if department == "BBMP":
        return "waste_management"
    if department == "POLICE" and "noise" in text:
        return "noise_disturbance"
    return "other"


def _has_issue_signal(transcript: str, department: str, emergency_type: str) -> bool:
    text = transcript.lower()
    if department != "OTHER" or emergency_type != "other":
        return True
    issue_terms = (
        "problem",
        "issue",
        "complaint",
        "grievance",
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
    )
    return any(term in text for term in issue_terms)


def _extract_location_hint(transcript: str) -> str:
    text = " ".join(transcript.split())
    lower = text.lower()
    best_index = -1
    best_marker = ""
    for marker in (" location is ", " in ", " at ", " near ", " from "):
        index = lower.rfind(marker)
        if index > best_index:
            best_index = index
            best_marker = marker
    if best_index >= 0:
        return _clean_location_hint(text[best_index + len(best_marker):])
    return ""


def _clean_location_hint(location: str) -> str:
    cleaned = location.strip(" .,:;")
    cleaned = re.split(
        r"\b(?:i need help|please help|that is all|thank you|thanks|can you help|just create ticket|create ticket|log ticket|raise ticket|go ahead|proceed)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .,:;")
    return cleaned


def _detect_text_language(transcript: str) -> str:
    text = transcript.lower()
    if any(term in text for term in ("hai", "nahi", "haan", "bijli", "paani", "shikayat")):
        return "hindi"
    if any(term in text for term in ("illa", "beku", "madam", "sari", "vidyut", "neeru", "haudu")):
        return "kannada"
    return "english"


def _sentiment_from_text(transcript: str, acoustic_score: float) -> str:
    text = transcript.lower()
    if any(term in text for term in ("scared", "fear", "afraid", "danger", "threat", "help now")):
        return "fear"
    if any(term in text for term in ("urgent", "immediately", "emergency", "right now", "bahut zaroori")):
        return "urgent"
    if any(term in text for term in ("angry", "fed up", "ridiculous", "again and again", "many times")):
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
    location = memory.get("landmark") or memory.get("area") or fallback_location
    issue = _issue_label(memory.get("issue"), language) if memory.get("issue") else fallback_issue

    if session.required_slot == "issue":
        if language == "hindi":
            return "कर्नाटक 1092 में आपका स्वागत है. मैं आपकी मदद करूंगी. कृपया अपनी शिकायत बताइए."
        if language == "kannada":
            return "ಕರ್ನಾಟಕ 1092 ಗೆ ಸ್ವಾಗತ. ನಾನು ನಿಮಗೆ ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ದೂರು ಹೇಳಿ."
        return "Welcome to Karnataka 1092. I will help you. Please tell me what happened."

    if session.required_slot in {"location", "landmark"}:
        if language == "hindi":
            return "मैं आपकी समस्या समझ गई. मैं तुरंत टिकट बनाने में मदद करूंगी. टिकट में कौन सा क्षेत्र और नजदीकी लैंडमार्क डालूं?"
        if language == "kannada":
            return "ನಿಮ್ಮ ಸಮಸ್ಯೆ ಅರ್ಥವಾಗಿದೆ. ತಕ್ಷಣ ಟಿಕೆಟ್ ಮಾಡಲು ಸಹಾಯ ಮಾಡುತ್ತೇನೆ. ಟಿಕೆಟ್‌ನಲ್ಲಿ ಯಾವ ಪ್ರದೇಶ ಮತ್ತು ಹತ್ತಿರದ ಗುರುತು ಹಾಕಲಿ?"
        return "I understand your problem. I will help create a ticket immediately. Which area and nearest landmark should I put on the ticket?"

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

    if session.required_slot == "confirmation":
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
        return f"Let me confirm: {issue} at {location}.{detail} I will route this to {department}. Is that correct?"

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


def _build_dispatch_message(session: CallSession) -> str:
    analysis = session.analysis_result
    language = _preferred_language(session, analysis.language_detected if analysis else None)
    department = (analysis.department if analysis else None) or session.department_assigned or "the concerned department"

    if language == "hindi":
        return f"आपका टिकट {session.ticket_id} {department} के साथ दर्ज हो गया है. स्थिति जानने के लिए 1092 पर यही नंबर बताएं. धन्यवाद."
    if language == "kannada":
        return f"ನಿಮ್ಮ ಟಿಕೆಟ್ {session.ticket_id} {department} ಗೆ ದಾಖಲಾಗಿದೆ. ಸ್ಥಿತಿ ತಿಳಿಯಲು 1092 ಗೆ ಕರೆ ಮಾಡಿ ಈ ಸಂಖ್ಯೆಯನ್ನು ಹೇಳಿ. ಧನ್ಯವಾದಗಳು."
    return f"Your ticket {session.ticket_id} has been logged with {department}. Check status by calling 1092 and quoting this number. Thank you for calling."


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
