"""
Samvaad 1092 — Core Subsystems
================================
All intelligence, security, and speech subsystems live here.

Modules:
    acoustic_guardian  — On-device distress detection (librosa + Wav2Vec2)
    llm_swarm          — Model-agnostic LLM cascade (Groq/Gemini/OpenRouter/DeepSeek)
    pii_scrubber       — Local PII redaction (Regex + IndicNER)
    sarvam_bridge      — Sarvam AI STT (Saaras V3) + TTS (Bulbul V3)
    verification_fsm   — The 1092 Verification State Machine
    database           — Async SQLite persistence for learning signals
"""

from .acoustic_guardian import AcousticGuardian, get_guardian
from .llm_swarm import ProviderFactory, get_factory
from .pii_scrubber import PIIScrubber, get_scrubber
from .sarvam_bridge import SarvamSTT, SarvamTTS, get_stt, get_tts
from .verification_fsm import VerificationEngine

__all__ = [
    "AcousticGuardian",
    "get_guardian",
    "ProviderFactory",
    "get_factory",
    "PIIScrubber",
    "get_scrubber",
    "SarvamSTT",
    "SarvamTTS",
    "get_stt",
    "get_tts",
    "VerificationEngine",
]
