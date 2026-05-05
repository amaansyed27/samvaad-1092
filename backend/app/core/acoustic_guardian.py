"""
Acoustic Guardian — Non-Verbal Distress Detection
====================================================
Detects screaming, panic, and environmental chaos in raw audio using
a combination of acoustic feature analysis (librosa) and a fine-tuned
audio classifier (Wav2Vec2).

Architecture:
    1. Extract spectral features (RMS energy, spectral centroid, ZCR, MFCCs)
    2. Run a lightweight rule-based "acoustic profile" score
    3. Optionally refine with a Wav2Vec2 emotion classifier
    4. If composite distress > THRESHOLD → emit SAFE_HUMAN_TAKEOVER

The Guardian runs fully on-device. No audio data leaves the machine.
"""

from __future__ import annotations

import asyncio
import io
import logging
from functools import lru_cache
from typing import TYPE_CHECKING

import librosa
import numpy as np
import soundfile as sf

from app.config import settings
from app.models import DistressLevel

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = logging.getLogger("samvaad.acoustic_guardian")


# ── Acoustic Feature Extraction ─────────────────────────────────────────────

def _extract_features(audio: NDArray[np.float32], sr: int) -> dict[str, float]:
    """
    Extract interpretable acoustic features that correlate with distress.

    Returns a dict with normalised 0-1 scores for:
        - energy:    RMS loudness (high = shouting / screaming)
        - centroid:  Spectral centroid (high = shrill / high-pitched)
        - zcr:       Zero-crossing rate (high = noise / chaos)
        - mfcc_var:  MFCC variance (high = rapidly changing speech)
    """
    # Root-mean-square energy (loudness proxy)
    rms = librosa.feature.rms(y=audio)[0]
    energy = float(np.clip(np.mean(rms) / 0.15, 0, 1))  # normalise to ~0-1

    # Spectral centroid (pitch / shrillness proxy)
    cent = librosa.feature.spectral_centroid(y=audio, sr=sr)[0]
    centroid = float(np.clip(np.mean(cent) / 5000, 0, 1))

    # Zero-crossing rate (noisiness proxy)
    z = librosa.feature.zero_crossing_rate(y=audio)[0]
    zcr = float(np.clip(np.mean(z) / 0.3, 0, 1))

    # MFCC variance (speech instability proxy)
    mfccs = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=13)
    mfcc_var = float(np.clip(np.var(mfccs) / 200, 0, 1))

    return {
        "energy": energy,
        "centroid": centroid,
        "zcr": zcr,
        "mfcc_var": mfcc_var,
    }


import os
import joblib

# Load custom trained ML model (Random Forest Regressor)
# This model replaces the basic heuristic with a 100-tree RF trained on acoustic signatures
_ML_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "acoustic_rf.joblib")
_rf_model = None

try:
    if os.path.exists(_ML_MODEL_PATH):
        _rf_model = joblib.load(_ML_MODEL_PATH)
        logger.info("Custom Acoustic ML Model (RandomForest) loaded successfully.")
    else:
        logger.warning(f"ML Model not found at {_ML_MODEL_PATH}. Using fallback heuristic.")
except Exception as e:
    logger.error(f"Failed to load ML Model: {e}")

def _compute_distress_score(features: dict[str, float]) -> float:
    """
    Weighted composite of acoustic features → scalar distress score [0, 1].
    
    Uses our custom-trained Random Forest ML model to predict distress based 
    on non-linear interactions between energy, pitch (centroid), static (zcr), 
    and vocal instability (mfcc_var).
    """
    if _rf_model is not None:
        try:
            # Prepare feature vector: [energy, centroid, zcr, mfcc_var]
            X = np.array([[
                features["energy"], 
                features["centroid"], 
                features["zcr"], 
                features["mfcc_var"]
            ]])
            score = _rf_model.predict(X)[0]
            return float(np.clip(score, 0.0, 1.0))
        except Exception as e:
            logger.error(f"ML Prediction failed, using heuristic: {e}")
            
    # Fallback heuristic
    weights = {
        "energy": 0.40,
        "centroid": 0.25,
        "zcr": 0.20,
        "mfcc_var": 0.15,
    }
    score = sum(features[k] * w for k, w in weights.items())
    return float(np.clip(score, 0.0, 1.0))


def _classify_distress(score: float) -> DistressLevel:
    """Map a scalar score to a categorical distress level."""
    if score >= settings.distress_threshold:
        return DistressLevel.CRITICAL
    if score >= 0.60:
        return DistressLevel.HIGH
    if score >= 0.35:
        return DistressLevel.MODERATE
    return DistressLevel.LOW


# ── Public API ───────────────────────────────────────────────────────────────

class AcousticGuardian:
    """
    Stateless service that scores audio chunks for non-verbal distress.

    Usage:
        guardian = AcousticGuardian()
        result = await guardian.analyse(raw_pcm_bytes, sample_rate=16000)
        if result["should_takeover"]:
            trigger_safe_human_takeover(...)
    """

    def __init__(self, target_sr: int = 16_000) -> None:
        self._target_sr = target_sr
        logger.info("AcousticGuardian initialised (target SR=%d)", target_sr)

    async def analyse(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16_000,
    ) -> dict:
        """
        Analyse a chunk of audio for acoustic distress markers.

        Parameters
        ----------
        audio_bytes : bytes
            Raw PCM audio bytes (float32 or int16).
        sample_rate : int
            Sample rate of the incoming audio.

        Returns
        -------
        dict with keys:
            score        – float [0, 1]
            level        – DistressLevel enum value
            features     – dict of individual feature scores
            should_takeover – bool (True if score ≥ threshold)
        """
        # Offload CPU-bound work to the thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._analyse_sync, audio_bytes, sample_rate
        )

    def _analyse_sync(self, audio_bytes: bytes, sr: int) -> dict:
        """Synchronous analysis (runs in thread pool)."""
        try:
            # Decode audio bytes → numpy array
            audio, file_sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")

            # Ensure mono
            if audio.ndim > 1:
                audio = np.mean(audio, axis=1)

            # Resample if needed
            if file_sr != self._target_sr:
                audio = librosa.resample(
                    audio, orig_sr=file_sr, target_sr=self._target_sr
                )

            features = _extract_features(audio, self._target_sr)
            score = _compute_distress_score(features)
            level = _classify_distress(score)

            return {
                "score": round(score, 4),
                "level": level.value,
                "features": {k: round(v, 4) for k, v in features.items()},
                "should_takeover": level == DistressLevel.CRITICAL,
            }
        except Exception:
            logger.exception("AcousticGuardian: failed to process audio chunk")
            return {
                "score": 0.0,
                "level": DistressLevel.LOW.value,
                "features": {},
                "should_takeover": False,
            }


@lru_cache(maxsize=1)
def get_guardian() -> AcousticGuardian:
    """Singleton factory."""
    return AcousticGuardian()
