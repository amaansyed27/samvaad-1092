"""
PII Scrubber — Local, Regex + NER-Based PII Redaction
=======================================================
**SECURITY INVARIANT**: No raw PII ever leaves this machine.
All text is scrubbed BEFORE being sent to any hosted LLM provider.

Strategy (defence in depth):
    Layer 1 — Regex patterns for structured Indian PII:
        • Aadhaar numbers (12-digit with optional spaces)
        • PAN card numbers
        • Indian mobile numbers (+91 / 0-prefixed)
        • Email addresses
        • Bank account / IFSC codes
        • Vehicle registration numbers (KA-XX-XX-XXXX)

    Layer 2 — Transformer-based NER for unstructured PII:
        • Person names (all scripts: Kannada, Hindi, English)
        • Addresses & location fragments
        • Organisation names

Both layers run entirely on the local device.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from app.models import PIIEntity

logger = logging.getLogger("samvaad.pii_scrubber")


# ══════════════════════════════════════════════════════════════════════════════
# Layer 1: Regex Patterns for Structured Indian PII
# ══════════════════════════════════════════════════════════════════════════════

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # Aadhaar: 12 digits, optionally grouped as 4-4-4
    (
        "AADHAAR",
        re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
        "[AADHAAR_REDACTED]",
    ),
    # PAN: 5 letters + 4 digits + 1 letter
    (
        "PAN",
        re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
        "[PAN_REDACTED]",
    ),
    # Indian mobile: +91 or 0 prefix + 10 digits
    (
        "PHONE",
        re.compile(r"(?:\+91[\s-]?|0)?[6-9]\d{9}\b"),
        "[PHONE_REDACTED]",
    ),
    # Email
    (
        "EMAIL",
        re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
        "[EMAIL_REDACTED]",
    ),
    # IFSC code
    (
        "IFSC",
        re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
        "[IFSC_REDACTED]",
    ),
    # Vehicle registration (Karnataka style: KA-XX-XX-XXXX)
    (
        "VEHICLE_REG",
        re.compile(r"\b[A-Z]{2}[\s-]?\d{2}[\s-]?[A-Z]{1,2}[\s-]?\d{4}\b"),
        "[VEHICLE_REDACTED]",
    ),
    # Bank account (8–18 digit sequences that aren't Aadhaar)
    (
        "BANK_ACCOUNT",
        re.compile(r"\b\d{8,18}\b"),
        "[ACCOUNT_REDACTED]",
    ),
]


def _regex_scrub(text: str) -> tuple[str, list[PIIEntity]]:
    """
    Apply all regex patterns and return scrubbed text + entity list.
    Patterns are applied in order; earlier matches take priority.
    """
    entities: list[PIIEntity] = []
    # Track already-matched spans to avoid overlapping redactions
    masked: set[tuple[int, int]] = set()

    for entity_type, pattern, replacement in _PATTERNS:
        for match in pattern.finditer(text):
            span = (match.start(), match.end())
            # Skip if this span overlaps with an already-matched one
            if any(s <= span[0] < e or s < span[1] <= e for s, e in masked):
                continue
            masked.add(span)
            entities.append(
                PIIEntity(
                    entity_type=entity_type,
                    original=match.group(),
                    replacement=replacement,
                    start=span[0],
                    end=span[1],
                )
            )

    # Replace from end to start to preserve indices
    sorted_entities = sorted(entities, key=lambda e: e.start, reverse=True)
    scrubbed = text
    for ent in sorted_entities:
        scrubbed = scrubbed[: ent.start] + ent.replacement + scrubbed[ent.end :]

    return scrubbed, entities


# ══════════════════════════════════════════════════════════════════════════════
# Layer 2: Transformer NER (lazy-loaded)
# ══════════════════════════════════════════════════════════════════════════════

_ner_pipeline = None


def _get_ner_pipeline():
    """Lazy-load the NER pipeline on first use."""
    global _ner_pipeline
    if _ner_pipeline is None:
        try:
            from transformers import pipeline

            _ner_pipeline = pipeline(
                "ner",
                model="ai4bharat/IndicNER",
                aggregation_strategy="simple",
                device=-1,  # CPU — no GPU required
            )
            logger.info("NER pipeline loaded: ai4bharat/IndicNER")
        except Exception:
            logger.warning(
                "Failed to load NER model — falling back to regex-only scrubbing. "
                "Install `transformers` and ensure model access for Layer 2."
            )
            _ner_pipeline = False  # sentinel: don't retry
    return _ner_pipeline if _ner_pipeline is not False else None


_NER_LABEL_MAP = {
    "PER": ("PERSON_NAME", "[NAME_REDACTED]"),
    "LOC": ("LOCATION", "[LOCATION_REDACTED]"),
    "ORG": ("ORGANISATION", "[ORG_REDACTED]"),
}


def _ner_scrub(text: str) -> tuple[str, list[PIIEntity]]:
    """
    Run transformer NER to catch unstructured PII (names, locations, orgs).
    Returns scrubbed text + entity list.
    """
    pipe = _get_ner_pipeline()
    if pipe is None:
        return text, []

    try:
        results = pipe(text)
    except Exception:
        logger.exception("NER inference failed")
        return text, []

    entities: list[PIIEntity] = []
    for ent in results:
        label = ent.get("entity_group", "")
        if label not in _NER_LABEL_MAP:
            continue
        entity_type, replacement = _NER_LABEL_MAP[label]
        entities.append(
            PIIEntity(
                entity_type=entity_type,
                original=ent["word"],
                replacement=replacement,
                start=ent["start"],
                end=ent["end"],
            )
        )

    # Replace from end to start
    sorted_entities = sorted(entities, key=lambda e: e.start, reverse=True)
    scrubbed = text
    for ent in sorted_entities:
        scrubbed = scrubbed[: ent.start] + ent.replacement + scrubbed[ent.end :]

    return scrubbed, entities


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

class PIIScrubber:
    """
    Defence-in-depth PII scrubber.

    Usage:
        scrubber = PIIScrubber()
        clean_text, entities = scrubber.scrub("My Aadhaar is 1234 5678 9012")
        # clean_text → "My Aadhaar is [AADHAAR_REDACTED]"
    """

    def scrub(self, text: str) -> tuple[str, list[PIIEntity]]:
        """
        Run both regex and NER layers. Returns (scrubbed_text, all_entities).

        **SECURITY**: This method MUST be called before sending text to any
        external LLM provider. Failure to do so is a security violation.
        """
        # Layer 1: Regex (fast, deterministic)
        text, regex_entities = _regex_scrub(text)

        # Layer 2: NER (catches names / locations the regex misses)
        text, ner_entities = _ner_scrub(text)

        all_entities = regex_entities + ner_entities
        logger.info(
            "PII scrub complete: %d entities redacted (regex=%d, ner=%d)",
            len(all_entities),
            len(regex_entities),
            len(ner_entities),
        )
        return text, all_entities

    def scrub_fast(self, text: str) -> tuple[str, list[PIIEntity]]:
        """
        Regex-only scrubber for live telephony turns.

        This keeps the phone call responsive while still redacting structured
        PII such as phone numbers, Aadhaar, PAN, email, IFSC, vehicles, and
        account numbers before downstream processing.
        """
        return _regex_scrub(text)


@lru_cache(maxsize=1)
def get_scrubber() -> PIIScrubber:
    """Singleton factory."""
    return PIIScrubber()
