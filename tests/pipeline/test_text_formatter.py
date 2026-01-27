"""Unit tests for the TextFormatter helper class.

Tests cover:
- Title generation from transcript with various inputs
- Device name formatting
- Text truncation with suffix
"""

import pytest

from src.pipeline.text_formatter import TextFormatter


class TestGenerateTitle:
    """Tests for TextFormatter.generate_title method."""

    def test_generate_title_from_short_transcript(self):
        """Verify title from short transcript is returned as-is."""
        title = TextFormatter.generate_title("Hello world.")
        assert title == "Hello world."

    def test_generate_title_truncates_long_transcript(self):
        """Verify long transcripts are truncated to ~15 words."""
        long_text = " ".join(["word"] * 50)
        title = TextFormatter.generate_title(long_text)

        words = title.replace("...", "").strip().split()
        assert len(words) <= 15
        assert title.endswith("...")

    def test_generate_title_uses_first_sentence_period(self):
        """Verify only first sentence is used (period delimiter)."""
        text = "This is the first sentence. This is the second."
        title = TextFormatter.generate_title(text)
        assert title == "This is the first sentence."

    def test_generate_title_uses_first_sentence_exclamation(self):
        """Verify exclamation is used as sentence delimiter when no period."""
        # Note: implementation prioritizes period over exclamation
        text = "Wow this is great!"
        title = TextFormatter.generate_title(text)
        assert title == "Wow this is great!"

    def test_generate_title_uses_first_sentence_question(self):
        """Verify question mark is used as sentence delimiter when no period."""
        # Note: implementation prioritizes period over question mark
        text = "Is this working?"
        title = TextFormatter.generate_title(text)
        assert title == "Is this working?"

    def test_generate_title_handles_none(self):
        """Verify None transcript produces default title."""
        title = TextFormatter.generate_title(None)
        assert title == "Voice Capture"

    def test_generate_title_handles_empty(self):
        """Verify empty transcript produces default title."""
        title = TextFormatter.generate_title("")
        assert title == "Voice Capture"

    def test_generate_title_handles_whitespace_only(self):
        """Verify whitespace-only transcript produces default title."""
        title = TextFormatter.generate_title("   \n\t  ")
        assert title == "Voice Capture"

    def test_generate_title_strips_leading_whitespace(self):
        """Verify leading whitespace is stripped."""
        title = TextFormatter.generate_title("   Hello world.")
        assert title == "Hello world."

    def test_generate_title_respects_max_words_parameter(self):
        """Verify custom max_words parameter is respected."""
        long_text = " ".join(["word"] * 20)
        title = TextFormatter.generate_title(long_text, max_words=5)

        words = title.replace("...", "").strip().split()
        assert len(words) == 5
        assert title.endswith("...")

    def test_generate_title_no_truncation_when_under_limit(self):
        """Verify no truncation when under word limit."""
        text = "Short sentence here"
        title = TextFormatter.generate_title(text, max_words=10)
        assert title == "Short sentence here"
        assert not title.endswith("...")

    def test_generate_title_long_first_sentence_truncated(self):
        """Verify long first sentence is still truncated."""
        # Long first sentence with no period
        long_sentence = " ".join(["word"] * 50) + "."
        title = TextFormatter.generate_title(long_sentence)

        words = title.replace("...", "").strip().split()
        assert len(words) <= 15


class TestFormatDeviceName:
    """Tests for TextFormatter.format_device_name method.

    Device passthrough: raw device strings are returned as-is.
    Only None/empty values fall back to 'Unknown'.
    """

    def test_format_device_passthrough_lowercase(self):
        """Verify lowercase device strings are returned as-is."""
        assert TextFormatter.format_device_name("watch") == "watch"
        assert TextFormatter.format_device_name("phone") == "phone"

    def test_format_device_passthrough_preserves_case(self):
        """Verify original casing is preserved."""
        assert TextFormatter.format_device_name("Apple Watch") == "Apple Watch"
        assert TextFormatter.format_device_name("iPhone") == "iPhone"
        assert TextFormatter.format_device_name("WATCH") == "WATCH"

    def test_format_device_passthrough_arbitrary(self):
        """Verify arbitrary device strings are passed through."""
        assert TextFormatter.format_device_name("tablet") == "tablet"
        assert TextFormatter.format_device_name("ipad") == "ipad"
        assert TextFormatter.format_device_name("mac") == "mac"

    def test_format_device_none(self):
        """Verify None returns 'Unknown'."""
        assert TextFormatter.format_device_name(None) == "Unknown"

    def test_format_device_empty_string(self):
        """Verify empty string returns 'Unknown'."""
        assert TextFormatter.format_device_name("") == "Unknown"


class TestTruncateText:
    """Tests for TextFormatter.truncate_text method."""

    def test_truncate_text_under_limit(self):
        """Verify text under limit is returned unchanged."""
        text = "Short text"
        result = TextFormatter.truncate_text(text, max_length=20)
        assert result == "Short text"

    def test_truncate_text_at_limit(self):
        """Verify text exactly at limit is returned unchanged."""
        text = "Exactly10c"  # 10 characters
        result = TextFormatter.truncate_text(text, max_length=10)
        assert result == "Exactly10c"

    def test_truncate_text_over_limit(self):
        """Verify text over limit is truncated with suffix."""
        text = "This is a longer text that needs truncation"
        result = TextFormatter.truncate_text(text, max_length=20)
        assert len(result) == 20
        assert result.endswith("...")

    def test_truncate_text_custom_suffix(self):
        """Verify custom suffix is used."""
        text = "This is a longer text"
        result = TextFormatter.truncate_text(text, max_length=15, suffix="[...]")
        assert len(result) == 15
        assert result.endswith("[...]")

    def test_truncate_text_empty_suffix(self):
        """Verify empty suffix works correctly."""
        text = "This is text"
        result = TextFormatter.truncate_text(text, max_length=8, suffix="")
        assert result == "This is "
        assert len(result) == 8

    def test_truncate_text_none_returns_none(self):
        """Verify None input returns None."""
        result = TextFormatter.truncate_text(None, max_length=10)
        assert result is None

    def test_truncate_text_empty_string(self):
        """Verify empty string is returned unchanged."""
        result = TextFormatter.truncate_text("", max_length=10)
        assert result == ""

    def test_truncate_text_max_length_smaller_than_suffix(self):
        """Verify behavior when max_length is smaller than suffix."""
        text = "Long text here"
        result = TextFormatter.truncate_text(text, max_length=2, suffix="...")
        # Should return truncated suffix
        assert result == ".."  # First 2 chars of "..."

    def test_truncate_text_preserves_content_before_truncation(self):
        """Verify the correct portion of text is preserved."""
        text = "Hello World"
        result = TextFormatter.truncate_text(text, max_length=8, suffix="...")
        assert result == "Hello..."
        assert result.startswith("Hello")
