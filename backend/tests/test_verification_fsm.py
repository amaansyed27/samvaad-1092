"""
Tests for the Verification State Machine.
"""

import pytest
from app.core.verification_fsm import VerificationEngine, InvalidTransition
from app.models import CallSession, VerificationState


@pytest.fixture
def engine():
    return VerificationEngine()


@pytest.fixture
def session():
    return CallSession()


class TestStateTransitions:
    """Verify the FSM enforces valid transition rules."""

    def test_init_to_listen(self, engine, session):
        assert session.state == VerificationState.INIT.value
        result = engine.start_listening(session)
        assert session.state == VerificationState.LISTEN.value
        assert result["event"] == "state_change"

    def test_listen_to_scrub(self, engine, session):
        engine.start_listening(session)
        result = engine.receive_transcript(session, "test transcript")
        assert session.state == VerificationState.SCRUB.value
        assert "test transcript" in session.raw_transcript

    def test_scrub_to_analyze(self, engine, session):
        engine.start_listening(session)
        engine.receive_transcript(session, "My Aadhaar is 1234 5678 9012")
        result = engine.scrub(session)
        assert session.state == VerificationState.ANALYZE.value
        assert "[AADHAAR_REDACTED]" in session.scrubbed_transcript

    def test_force_takeover(self, engine, session):
        engine.start_listening(session)
        result = engine.force_takeover(session, "Test takeover")
        assert session.state == VerificationState.HUMAN_TAKEOVER.value
        assert result["event"] == "SAFE_HUMAN_TAKEOVER"

    def test_confirm_verified(self, engine, session):
        # Manually set state to WAIT_FOR_CONFIRM for testing
        session.state = VerificationState.WAIT_FOR_CONFIRM.value
        result = engine.confirm(session, confirmed=True)
        assert session.state == VerificationState.VERIFIED.value
        assert result["event"] == "VERIFIED"

    def test_confirm_rejected_loops_back(self, engine, session):
        session.state = VerificationState.WAIT_FOR_CONFIRM.value
        result = engine.confirm(session, confirmed=False)
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
