"""
Tests for the PII Scrubber — verifies both regex and NER layers.
"""

import pytest
from app.core.pii_scrubber import PIIScrubber


@pytest.fixture
def scrubber():
    return PIIScrubber()


class TestRegexLayer:
    """Layer 1: Regex pattern tests for structured Indian PII."""

    def test_aadhaar_with_spaces(self, scrubber):
        text = "My Aadhaar number is 1234 5678 9012"
        clean, entities = scrubber.scrub(text)
        assert "[AADHAAR_REDACTED]" in clean
        assert "1234 5678 9012" not in clean
        assert any(e.entity_type == "AADHAAR" for e in entities)

    def test_aadhaar_without_spaces(self, scrubber):
        text = "Aadhaar: 123456789012"
        clean, entities = scrubber.scrub(text)
        assert "[AADHAAR_REDACTED]" in clean or "[ACCOUNT_REDACTED]" in clean

    def test_pan_card(self, scrubber):
        text = "PAN card is ABCDE1234F"
        clean, entities = scrubber.scrub(text)
        assert "[PAN_REDACTED]" in clean
        assert "ABCDE1234F" not in clean

    def test_indian_mobile(self, scrubber):
        text = "Call me on +91 9876543210"
        clean, entities = scrubber.scrub(text)
        assert "[PHONE_REDACTED]" in clean
        assert "9876543210" not in clean

    def test_email(self, scrubber):
        text = "Email: test@example.com"
        clean, entities = scrubber.scrub(text)
        assert "[EMAIL_REDACTED]" in clean
        assert "test@example.com" not in clean

    def test_vehicle_registration(self, scrubber):
        text = "Vehicle number KA 01 AB 1234"
        clean, entities = scrubber.scrub(text)
        assert "[VEHICLE_REDACTED]" in clean

    def test_no_pii(self, scrubber):
        text = "There is a fire in the building"
        clean, entities = scrubber.scrub(text)
        # Should pass through with minimal or no redaction
        assert "fire" in clean
        assert "building" in clean

    def test_multiple_pii(self, scrubber):
        text = "I am calling from +91 9876543210, my PAN is ABCDE1234F"
        clean, entities = scrubber.scrub(text)
        assert "[PHONE_REDACTED]" in clean
        assert "[PAN_REDACTED]" in clean
        assert len(entities) >= 2

    def test_ifsc_code(self, scrubber):
        text = "IFSC: SBIN0001234"
        clean, entities = scrubber.scrub(text)
        assert "[IFSC_REDACTED]" in clean


class TestScrubberIntegrity:
    """Ensure scrubbing doesn't corrupt non-PII content."""

    def test_preserves_emergency_details(self, scrubber):
        text = "There is a medical emergency at MG Road, someone has collapsed"
        clean, _ = scrubber.scrub(text)
        assert "medical emergency" in clean
        assert "collapsed" in clean

    def test_kannada_text_passthrough(self, scrubber):
        text = "ನನ್ನ ಮನೆಯಲ್ಲಿ ಬೆಂಕಿ ಹತ್ತಿದೆ"  # "There is a fire in my house"
        clean, _ = scrubber.scrub(text)
        assert "ಬೆಂಕಿ" in clean  # "fire" should remain

    def test_hindi_text_passthrough(self, scrubber):
        text = "मेरे घर में आग लगी है"  # "There is a fire in my house"
        clean, _ = scrubber.scrub(text)
        assert "आग" in clean  # "fire" should remain
