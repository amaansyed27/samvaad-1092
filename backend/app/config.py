"""
Samvaad 1092 — Centralised Configuration
=========================================
All tuneable parameters live here. Values are loaded from environment
variables (or `.env`) via pydantic-settings. Secrets never touch source control.
"""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Immutable, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM Provider Keys ────────────────────────────────────────────────
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""

    # ── Provider Models ──────────────────────────────────────────────────
    gemini_model: str = "gemini-3-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    deepseek_model: str = "deepseek-v4-flash"

    # ── Sarvam AI (Indian DPI) ───────────────────────────────────────────
    sarvam_api_key: str = ""
    sarvam_stt_model: str = "saaras:v3"
    sarvam_stt_mode: str = "transcribe"      # transcribe | translate | codemix
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_speaker: str = "shubh"
    sarvam_tts_language: str = "kn-IN"       # default to Kannada

    # ── Server ───────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # ── Acoustic Guardian ────────────────────────────────────────────────
    distress_threshold: float = 0.85
    wav2vec2_model: str = "facebook/wav2vec2-base"

    # ── PII Scrubber ─────────────────────────────────────────────────────
    pii_ner_model: str = "ai4bharat/IndicNER"

    # ── Database (Learning Signals) ──────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./samvaad_1092.db"

    # ── Dashboard ────────────────────────────────────────────────────────
    dashboard_origin: str = "http://localhost:5173"


settings = Settings()
