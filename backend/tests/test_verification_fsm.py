"""
Tests for the Verification State Machine.
"""

import pytest
from app.config import settings
from app.core.location_resolver import resolve_location_candidates
from app.core.verification_fsm import (
    VerificationEngine,
    InvalidTransition,
    _build_fast_analysis,
    _build_dispatch_message,
    _build_restatement,
    _detect_confirmation_intent,
    _is_specific_location,
    apply_geo_pin_to_session,
)
from app.ws.call_handler import _repair_locked_language_transcript
from app.models import AnalysisResult, CallSession, VerificationState


@pytest.fixture
def engine():
    return VerificationEngine()


@pytest.fixture
def session():
    return CallSession()


@pytest.fixture(autouse=True)
def disable_network_geocoder():
    original = settings.location_geocoder_provider
    settings.location_geocoder_provider = "disabled"
    yield
    settings.location_geocoder_provider = original


class TestStateTransitions:
    """Verify the FSM enforces valid transition rules."""

    def test_init_to_listen(self, engine, session):
        assert session.state == VerificationState.INIT.value
        result = engine.start_listening(session)
        assert session.state == VerificationState.LISTEN.value
        assert result["event"] == "state_change"

    @pytest.mark.asyncio
    async def test_listen_to_scrub(self, engine, session):
        engine.start_listening(session)
        result = await engine.receive_transcript(session, "test transcript")
        assert session.state == VerificationState.SCRUB.value
        assert "test transcript" in session.raw_transcript

    @pytest.mark.asyncio
    async def test_scrub_to_analyze(self, engine, session):
        engine.start_listening(session)
        await engine.receive_transcript(session, "My Aadhaar is 1234 5678 9012")
        result = engine.scrub(session)
        assert session.state == VerificationState.ANALYZE.value
        assert "[AADHAAR_REDACTED]" in session.scrubbed_transcript

    def test_force_takeover(self, engine, session):
        engine.start_listening(session)
        result = engine.force_takeover(session, "Test takeover")
        assert session.state == VerificationState.HUMAN_TAKEOVER.value
        assert result["event"] == "SAFE_HUMAN_TAKEOVER"

    @pytest.mark.asyncio
    async def test_confirm_verified(self, engine, session):
        # Manually set state to WAIT_FOR_CONFIRM for testing
        session.state = VerificationState.WAIT_FOR_CONFIRM.value
        result = await engine.confirm(session, confirmed=True)
        assert session.state == VerificationState.VERIFIED.value
        assert result["event"] == "VERIFIED"

    @pytest.mark.asyncio
    async def test_confirm_rejected_loops_back(self, engine, session):
        session.state = VerificationState.WAIT_FOR_CONFIRM.value
        result = await engine.confirm(session, confirmed=False)
        assert session.state == VerificationState.LISTEN.value


class TestInvalidTransitions:
    """Verify the FSM rejects invalid transitions."""

    def test_cannot_skip_scrub(self, engine, session):
        engine.start_listening(session)
        with pytest.raises(InvalidTransition):
            engine.scrub(session)  # Should fail: LISTEN → ANALYZE (skipping SCRUB)

    def test_verified_is_terminal(self, engine, session):
        session.state = VerificationState.VERIFIED.value
        with pytest.raises(InvalidTransition):
            engine.start_listening(session)


class TestHackathonGuardrails:
    def test_location_guardrail_rejects_broad_area_accepts_landmark(self):
        assert not _is_specific_location("Whitefield")
        assert not _is_specific_location("Fourth district")
        assert _is_specific_location("Whitefield near Vydehi hospital")
        assert _is_specific_location("4th cross Indiranagar")

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("yes correct", True),
            ("haan sahi hai", True),
            ("haudu sari", True),
            ("हाँ सही है", True),
            ("ಹೌದು ಸರಿ", True),
            ("no wrong", False),
            ("nahi galat hai", False),
            ("illa wrong", False),
            ("नहीं गलत है", False),
            ("ಇಲ್ಲ ತಪ್ಪು", False),
        ],
    )
    def test_confirmation_classifier_multilingual(self, text, expected):
        assert _detect_confirmation_intent(text) is expected

    def test_confirmation_ignores_filler_with_extra_details(self):
        assert _detect_confirmation_intent("ok my location is Whitefield") is None
        assert _detect_confirmation_intent("no the location is near Vydehi hospital") is None

    def test_vague_issue_requires_clarification_not_ticket_closure(self, session):
        session.scrubbed_transcript = "I have a problem"
        data = _build_fast_analysis(session, session.scrubbed_transcript, 0.1)
        assert data["needs_clarification"] is True
        assert session.required_slot in {"issue", "location"}

    def test_power_cut_at_my_house_asks_for_location_detail(self, session):
        session.scrubbed_transcript = "I am facing too many electrical cuts at my house"
        data = _build_fast_analysis(session, session.scrubbed_transcript, 0.2)
        assert data["department"] == "BESCOM"
        assert data["emergency_type"] == "power_outage"
        assert data["needs_clarification"] is True
        assert session.required_slot == "landmark"

    def test_ticket_closure_has_lookup_instruction_and_courtesy(self, session):
        session.analysis_result = AnalysisResult(
            department="BESCOM",
            language_detected="english",
            emergency_type="power_outage",
        )
        message = _build_dispatch_message(session)
        assert session.ticket_id in message
        assert "1092" in message
        assert "representative will contact you on this same number" in message
        assert "sent by SMS" in message
        assert "Thank you" in message

    def test_power_issue_deterministic_department_overrides_bad_ml_route(self, session):
        session.department_assigned = "BBMP"
        data = _build_fast_analysis(session, "I am facing too many electrical cuts at my house", 0.1)
        assert data["department"] == "BESCOM"
        assert session.conversation_memory["department"] == "BESCOM"

    def test_location_only_does_not_create_waste_issue(self, session):
        session.preferred_language_code = "kn-IN"
        session.preferred_language_label = "kannada"
        data = _build_fast_analysis(session, "Whitefield", 0.1)
        assert data["department"] == "OTHER"
        assert data["emergency_type"] == "other"
        assert data["needs_clarification"] is True
        assert session.required_slot == "issue"
        assert session.conversation_memory["issue"] == ""
        assert session.conversation_memory["area"] == "Whitefield"

    def test_kannada_transliteration_power_routes_bescom(self, session):
        session.preferred_language_code = "kn-IN"
        session.preferred_language_label = "kannada"
        data = _build_fast_analysis(session, "Haudu, nanage vidyut kaḍitavide.", 0.2)
        assert data["department"] == "BESCOM"
        assert data["emergency_type"] == "power_outage"
        assert data["language_detected"] == "kannada"
        assert data["needs_clarification"] is True
        assert session.required_slot in {"location", "landmark"}

    def test_kannada_locked_stt_hallucination_is_repaired(self, session):
        session.preferred_language_code = "kn-IN"
        session.preferred_language_label = "kannada"
        session.required_slot = "issue"
        repaired = _repair_locked_language_transcript(session, "How do you do?")
        assert "vidyut" in repaired
        assert _build_fast_analysis(session, repaired, 0.2)["department"] == "BESCOM"

    def test_warm_location_prompt_for_home_power_cut(self, session):
        session.scrubbed_transcript = "I am facing too many electrical cuts at my house"
        data = _build_fast_analysis(session, session.scrubbed_transcript, 0.2)
        session.analysis_result = AnalysisResult(**data)
        message = _build_restatement(session)
        assert "I understand your problem" in message
        assert "nearest landmark" in message

    def test_specific_location_asks_optional_detail_before_confirmation(self, session):
        session.scrubbed_transcript = "I am facing too many power cuts near Whitefield Vydehi hospital"
        data = _build_fast_analysis(session, session.scrubbed_transcript, 0.2)
        assert data["department"] == "BESCOM"
        assert data["needs_clarification"] is True
        assert session.required_slot == "started_at_or_time"
        assert session.conversation_memory["ticket_ready"] is True

    def test_just_create_ticket_skips_optional_questions(self, session):
        session.conversation_memory = {
            "issue": "power_outage",
            "department": "BESCOM",
            "area": "Whitefield",
            "landmark": "Whitefield near Vydehi hospital",
            "ticket_ready": True,
        }
        session.department_assigned = "BESCOM"
        data = _build_fast_analysis(session, "Just create ticket", 0.2)
        assert data["needs_clarification"] is False
        assert session.required_slot == "confirmation"
        assert session.conversation_memory["skip_optional"] is True

    def test_previous_complaint_and_authority_details_saved(self, session):
        session.conversation_memory = {
            "issue": "power_outage",
            "department": "BESCOM",
            "area": "Whitefield",
            "landmark": "Whitefield near Vydehi hospital",
            "ticket_ready": True,
        }
        session.department_assigned = "BESCOM"
        _build_fast_analysis(session, "I called BESCOM before, ticket 123", 0.2)
        assert session.conversation_memory["authority_contacted"] == "BESCOM"
        assert "ticket 123" in session.conversation_memory["previous_complaint"].lower()

    def test_time_details_do_not_overwrite_location(self, session):
        text = (
            "I am facing too many electrical cuts at my house. "
            "45, fifth cross near Espelad Apartments, Indiranagar. "
            "It has been happening for the past week and we have faced "
            "7 continuous cuts in 3 days and each cut has lasted over 3 hours."
        )
        data = _build_fast_analysis(session, text, 0.2)
        memory = session.conversation_memory

        assert data["department"] == "BESCOM"
        assert memory["area"] == "Indiranagar"
        assert "Espelad Apartments" in memory["landmark"]
        assert "3 days" not in memory["landmark"]
        assert "past week" in memory["started_at_or_time"]
        assert "7 continuous cuts in 3 days" in memory["frequency"]
        assert memory["ticket_ready"] is True

    def test_attempt_details_do_not_overwrite_location(self, session):
        session.conversation_memory = {
            "issue": "power_outage",
            "department": "BESCOM",
            "area": "Indiranagar",
            "landmark": "45, fifth cross near Espelad Apartments, Indiranagar",
            "ticket_ready": True,
        }
        session.department_assigned = "BESCOM"
        _build_fast_analysis(
            session,
            "We have tried contacting BESCOM, but they have been extremely unhelpful and very rude with us.",
            0.2,
        )
        memory = session.conversation_memory
        assert memory["area"] == "Indiranagar"
        assert "Espelad Apartments" in memory["landmark"]
        assert memory["authority_contacted"] == "BESCOM"
        assert memory["sentiment"] == "angry"
        assert memory["caller_tried"].startswith("We have tried contacting BESCOM")

    def test_priority_uses_described_impact_not_only_issue_type(self, session):
        text = (
            "Power cuts at 45 fifth cross near Espelad Apartments Indiranagar. "
            "It has been happening for the past week with 7 continuous cuts in 3 days, "
            "each cut lasted over 3 hours, and BESCOM was rude when we called."
        )
        data = _build_fast_analysis(session, text, 0.2)
        assert data["department"] == "BESCOM"
        assert data["priority"] == "HIGH"
        assert "long service interruption" in data["priority_reason"]
        assert data["empathy_note"]

    def test_unsafe_streetlight_route_asks_for_exact_location_first(self, session):
        text = (
            "There are no street lights on the road from the metro to my house. "
            "I have to walk there at night. It's a very shady area and I do not feel safe. "
            "People keep staring at me, please help."
        )
        data = _build_fast_analysis(session, text, 0.35)
        memory = session.conversation_memory
        session.analysis_result = AnalysisResult(**data)
        message = _build_restatement(session)

        assert data["department"] == "BBMP"
        assert data["emergency_type"] == "streetlights"
        assert data["priority"] == "HIGH"
        assert data["sentiment"] == "fear"
        assert data["requires_immediate_takeover"] is False
        assert data["needs_clarification"] is True
        assert session.required_slot == "landmark"
        assert memory["ticket_ready"] is False
        assert memory["location_validation_status"] == "needs_correction"
        assert "staring" not in memory["landmark"].lower()
        assert "metro station" in message

    def test_dummy_prank_call_gets_guardrail_warning(self, session):
        data = _build_fast_analysis(session, "this is a prank test call haha no issue", 0.1)
        assert data["abuse_action"] in {"WARN", "BLACKLIST_REVIEW"}
        assert data["needs_clarification"] is True
        assert session.required_slot == "abuse_warning"
        assert "prank" in data["abuse_reason"]

    def test_ration_card_routes_to_food_civil_supplies(self, session):
        data = _build_fast_analysis(
            session,
            "My ration card application is pending for two months in Mysuru",
            0.2,
        )
        memory = session.conversation_memory
        assert data["request_type"] == "grievance"
        assert data["department"] == "FOOD_CIVIL_SUPPLIES"
        assert data["line_department"] == "Food and Civil Supplies department"
        assert data["emergency_type"] == "ration_card"
        assert memory["service_or_scheme"] == "ration card"
        assert memory["area"] == "Mysuru"

    def test_ration_card_mobile_reference_moves_to_clean_confirmation(self, session):
        _build_fast_analysis(session, "My ration card application is pending for 2 months in Mysuru", 0.2)
        assert session.required_slot == "application_or_reference"
        session.optional_detail_count = 1

        data = _build_fast_analysis(session, "Yes, it is linked with the same mobile number.", 0.2)
        session.analysis_result = AnalysisResult(**data)
        message = _build_restatement(session)
        memory = session.conversation_memory

        assert session.required_slot == "confirmation"
        assert memory["application_or_reference"] == "linked with caller mobile number"
        assert memory["area"] == "Mysuru"
        assert memory["landmark"] == ""
        assert memory["started_at_or_time"] == "pending for 2 months"
        assert "same mobile" not in message.lower()
        assert "Mysuru. Yes" not in message
        assert "Food and Civil Supplies department" in message

    def test_labour_wages_routes_to_labour_department(self, session):
        data = _build_fast_analysis(
            session,
            "The labour office is not responding about unpaid wages in Peenya",
            0.2,
        )
        assert data["department"] == "LABOUR"
        assert data["emergency_type"] == "labour_grievance"
        assert session.conversation_memory["service_or_scheme"] in {"wages complaint", "labour office"}

    def test_health_service_priority_for_refused_medicine(self, session):
        data = _build_fast_analysis(
            session,
            "Government hospital staff refused medicine for my child in Jayanagar",
            0.2,
        )
        assert data["department"] == "HEALTH"
        assert data["emergency_type"] == "health_service"
        assert data["specialized_helpline"] == "104"
        assert data["priority"] in {"MEDIUM", "HIGH"}
        assert "health" in data["priority_reason"].lower()

    def test_pension_delay_routes_to_social_welfare(self, session):
        data = _build_fast_analysis(
            session,
            "My old age pension has not been received for three months in Tumakuru",
            0.2,
        )
        assert data["department"] == "SOCIAL_WELFARE"
        assert data["emergency_type"] == "pension_delay"
        assert data["request_type"] == "grievance"

    def test_someone_following_now_triggers_emergency_referral(self, session):
        data = _build_fast_analysis(
            session,
            "Someone is following me right now near Majestic bus stop",
            0.4,
        )
        assert data["request_type"] == "emergency_referral"
        assert data["department"] == "POLICE"
        assert data["specialized_helpline"] == "100"
        assert data["requires_immediate_takeover"] is True

    def test_contaminated_water_with_sick_child_adds_health_note(self, session):
        data = _build_fast_analysis(
            session,
            "Water is contaminated near Whitefield and my child is sick",
            0.3,
        )
        assert data["department"] == "BWSSB"
        assert data["secondary_department"] == "HEALTH"
        assert data["priority"] in {"MEDIUM", "HIGH"}

    @pytest.mark.parametrize(
        ("text", "department"),
        [
            ("bijli cut near Whitefield", "BESCOM"),
            ("paani contamination in Indiranagar", "BWSSB"),
            ("neeru problem in Jayanagar", "BWSSB"),
            ("ration card pending in Mysuru", "FOOD_CIVIL_SUPPLIES"),
            ("pension not received in Hubballi", "SOCIAL_WELFARE"),
            ("hospital refused medicine in Jayanagar", "HEALTH"),
        ],
    )
    def test_public_service_code_mix_terms_route(self, session, text, department):
        data = _build_fast_analysis(session, text, 0.2)
        assert data["department"] == department

    def test_takeover_event_includes_spoken_handoff(self, engine, session):
        event = engine.force_takeover(session, "High urgency or distress detected")
        assert event["event"] == "SAFE_HUMAN_TAKEOVER"
        assert "human operator" in event["assistant_message"]
        assert "stay on the line" in event["assistant_message"].lower()

    def test_high_distress_safety_issue_requires_takeover(self, session):
        data = _build_fast_analysis(
            session,
            "There is sparking from an electric wire down near the school and it is unsafe",
            0.8,
        )
        assert data["priority"] == "HIGH"
        assert data["requires_immediate_takeover"] is True

    def test_structured_address_and_landmark_are_combined(self, session):
        text = (
            "Address: No. 45, 5th Cross, Indiranagar, Bengaluru, Karnataka 560038 "
            "Landmark: Near Esplanade Apartments on 100 Feet Road."
        )
        data = _build_fast_analysis(session, f"Power cuts at my house. {text}", 0.2)
        memory = session.conversation_memory
        assert data["needs_clarification"] is True  # optional detail, not location correction
        assert memory["ticket_ready"] is True
        assert memory["area"] == "Indiranagar"
        assert "No. 45" in memory["landmark"]
        assert "Esplanade Apartments" in memory["landmark"]
        assert memory["location_validation_status"] == "verified_format"
        assert memory["location_confidence"] >= 0.9

    @pytest.mark.parametrize(
        "location",
        [
            "Airport",
            "Kempegowda International Airport",
            "Vidhan Sabha",
            "Vidhana Soudha",
        ],
    )
    def test_major_landmark_requires_more_location_detail(self, session, location):
        data = _build_fast_analysis(session, f"Power cut at {location}", 0.2)
        memory = session.conversation_memory
        assert data["needs_clarification"] is True
        assert session.required_slot == "landmark"
        assert memory["ticket_ready"] is False
        assert memory["location_validation_status"] == "needs_correction"
        assert "too broad" in memory["location_validation_reason"].lower()

    def test_fake_location_cue_requires_correction(self, session):
        data = _build_fast_analysis(
            session,
            "Power cut at Whitefield near Vydehi hospital but this is a dummy location",
            0.2,
        )
        memory = session.conversation_memory
        assert data["needs_clarification"] is True
        assert memory["ticket_ready"] is False
        assert memory["location_validation_status"] == "needs_correction"
        assert "fake" in memory["location_validation_reason"].lower()

    def test_hindi_language_lock_uses_hindi_prompts(self, engine, session):
        engine.set_language(session, "hi-IN")
        session.conversation_memory = {
            "issue": "power_outage",
            "department": "BESCOM",
            "area": "Whitefield",
            "landmark": "Vydehi hospital",
            "ticket_ready": True,
        }
        session.department_assigned = "BESCOM"
        data = _build_fast_analysis(session, "Whitefield near Vydehi hospital", 0.2)
        session.analysis_result = AnalysisResult(**data)
        message = _build_restatement(session)
        assert "कब शुरू हुआ" in message
        assert "I can log" not in message

    def test_kannada_language_lock_uses_kannada_confirmation(self, engine, session):
        engine.set_language(session, "kn-IN")
        session.conversation_memory = {
            "issue": "power_outage",
            "department": "BESCOM",
            "area": "Whitefield",
            "landmark": "Vydehi hospital",
            "ticket_ready": True,
            "skip_optional": True,
        }
        session.department_assigned = "BESCOM"
        data = _build_fast_analysis(session, "just create ticket", 0.2)
        session.analysis_result = AnalysisResult(**data)
        message = _build_restatement(session)
        assert "ನಾನು ದೃಢೀಕರಿಸುತ್ತೇನೆ" in message
        assert "Let me confirm" not in message

    def test_misheard_landmark_requires_map_confirmation(self, session):
        data = _build_fast_analysis(
            session,
            "Power cuts near Espelad Apartments",
            0.2,
        )
        memory = session.conversation_memory
        assert data["department"] == "BESCOM"
        assert session.required_slot == "location_confirm"
        assert data["needs_clarification"] is True
        assert memory["location_validation_status"] == "needs_map_confirmation"
        assert memory["map_candidates"][0]["name"] == "Esplanade Apartments"

    def test_confirmed_map_candidate_verifies_location(self, session):
        _build_fast_analysis(
            session,
            "Power cuts near Espelad Apartments",
            0.2,
        )
        data = _build_fast_analysis(session, "yes that is correct", 0.1)
        memory = session.conversation_memory
        assert data["needs_clarification"] is True
        assert data["needs_clarification"] == (session.required_slot == "started_at_or_time")
        assert memory["location_validation_status"] == "map_confirmed"
        assert memory["location_confirmed"] is True
        assert memory["ticket_ready"] is True

    def test_geo_pin_marks_location_as_pin_verified(self, session):
        session.conversation_memory = {
            "issue": "power_outage",
            "department": "BESCOM",
        }
        memory = apply_geo_pin_to_session(
            session,
            {"lat": 12.9784, "lng": 77.6408, "accuracy_m": 35},
        )
        assert memory["location_validation_status"] == "pin_verified"
        assert memory["ticket_ready"] is True
        assert session.call_slots["geo_pin"]["lat"] == 12.9784

    def test_dynamic_geocoder_candidate_is_used_before_local_fallback(self, monkeypatch):
        settings.location_geocoder_provider = "nominatim"

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [
                    {
                        "name": "Dynamic Ward Office",
                        "display_name": "Dynamic Ward Office, HSR Layout, Bengaluru, Karnataka, India",
                        "lat": "12.9121",
                        "lon": "77.6446",
                        "importance": 0.7,
                        "category": "office",
                        "type": "government",
                        "address": {"suburb": "HSR Layout", "city": "Bengaluru"},
                    }
                ]

        monkeypatch.setattr("app.core.location_resolver.httpx.get", lambda *args, **kwargs: FakeResponse())
        candidates = resolve_location_candidates("dynamic ward office hsr layout")
        assert candidates[0]["source"] == "nominatim"
        assert candidates[0]["name"] == "Dynamic Ward Office"
        assert candidates[0]["area"] == "HSR Layout"

    def test_optional_time_answer_does_not_pollute_landmark(self, session):
        _build_fast_analysis(
            session,
            "Power cuts at Esplanade Apartments on 100 Feet Road",
            0.2,
        )
        data = _build_fast_analysis(
            session,
            "It occurs for the past 2 weeks and over the past 3 days continuously",
            0.2,
        )
        memory = session.conversation_memory
        assert data["department"] == "BESCOM"
        assert "It occurs" not in memory["landmark"]
        assert memory["area"] == "Indiranagar"
        assert memory["started_at_or_time"]

    @pytest.mark.asyncio
    async def test_confirmation_question_gets_clean_explanation(self, engine, session):
        engine.start_listening(session)
        data = _build_fast_analysis(
            session,
            "Power cuts at Esplanade Apartments on 100 Feet Road for the past 2 weeks",
            0.2,
        )
        session.analysis_result = AnalysisResult(**data)
        session.state = VerificationState.WAIT_FOR_CONFIRM.value
        session.required_slot = "confirmation"
        event = await engine.receive_transcript(session, "What do you mean by it occurs?")
        assert event["event"] == "clarification_required"
        assert "Sorry, I meant" in event["assistant_message"]
        assert "It occurs" not in event["assistant_message"]
