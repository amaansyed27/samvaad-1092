"""
Regression tests for Twilio PSTN turn-taking.
"""

from app.models import CallSession
from app.ws.call_handler import _is_twilio_noise_transcript
from app.ws.twilio_handler import (
    TWILIO_BARGE_IN_CHUNKS,
    TWILIO_SILENCE_END_CHUNKS,
    _twilio_vad_decision,
)


def test_background_noise_during_assistant_playback_does_not_start_speech():
    candidate_chunks = 0
    blocked_chunks = 0

    for _ in range(20):
        is_speech, candidate_chunks, blocked_chunks, barge_in = _twilio_vad_decision(
            rms=450,
            speech_active=False,
            candidate_chunks=candidate_chunks,
            input_blocked=True,
            blocked_chunks=blocked_chunks,
        )
        assert not is_speech
        assert not barge_in


def test_loud_sustained_audio_during_assistant_playback_triggers_barge_in():
    candidate_chunks = 0
    blocked_chunks = 0
    barge_in = False

    for _ in range(TWILIO_BARGE_IN_CHUNKS):
        is_speech, candidate_chunks, blocked_chunks, barge_in = _twilio_vad_decision(
            rms=2200,
            speech_active=False,
            candidate_chunks=candidate_chunks,
            input_blocked=True,
            blocked_chunks=blocked_chunks,
        )

    assert is_speech
    assert barge_in


def test_one_second_pause_does_not_end_twilio_turn():
    silence_chunks = 0
    candidate_chunks = 0
    blocked_chunks = 0

    for _ in range(TWILIO_SILENCE_END_CHUNKS - 1):
        is_speech, candidate_chunks, blocked_chunks, _ = _twilio_vad_decision(
            rms=0,
            speech_active=True,
            candidate_chunks=candidate_chunks,
            input_blocked=False,
            blocked_chunks=blocked_chunks,
        )
        if not is_speech:
            silence_chunks += 1

    assert silence_chunks < TWILIO_SILENCE_END_CHUNKS


def test_short_filler_transcript_is_ignored_before_pipeline():
    session = CallSession()
    session.required_slot = "frequency"

    assert _is_twilio_noise_transcript(session, "that, uh,")
    assert _is_twilio_noise_transcript(session, "Okay.")

    session.required_slot = "confirmation"
    assert not _is_twilio_noise_transcript(session, "Okay.")
