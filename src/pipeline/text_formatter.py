"""Text formatting utilities for capture processing.

Extracted from orchestrator.py as part of work item 6.6 to improve
class cohesion and reduce orchestrator complexity.

Provides utilities for:
- Title generation from transcript text
- Device name formatting for display
- Text truncation with suffix
"""

from typing import Optional


class TextFormatter:
    """Text formatting utilities for capture processing.

    Provides static methods for common text transformations used
    during voice capture processing.
    """

    @staticmethod
    def generate_title(transcript: Optional[str], max_words: int = 15) -> str:
        """Generate a title from the transcript text.

        Extracts the first sentence or truncates to max_words if no
        sentence boundary is found within the limit.

        Args:
            transcript: The transcript text to generate title from.
            max_words: Maximum number of words in the title.

        Returns:
            A title string. Returns "Voice Capture" if transcript is
            empty or None.
        """
        if not transcript:
            return "Voice Capture"

        # Find first sentence
        text = transcript.strip()
        for delimiter in [".", "!", "?"]:
            pos = text.find(delimiter)
            if pos != -1:
                text = text[: pos + 1]
                break

        # Limit to max_words
        words = text.split()
        if len(words) > max_words:
            text = " ".join(words[:max_words]) + "..."

        return text or "Voice Capture"

    @staticmethod
    def format_device_name(device: Optional[str]) -> str:
        """Format device string for display.

        Normalizes device names to title case for known devices,
        or returns "Unknown" for unrecognized devices.

        Args:
            device: Raw device string (e.g., "watch", "phone").

        Returns:
            Formatted device name (e.g., "Watch", "Phone", "Unknown").
        """
        if not device:
            return "Unknown"

        device_lower = device.lower()
        if device_lower == "watch":
            return "Watch"
        elif device_lower == "phone":
            return "Phone"
        else:
            return "Unknown"

    @staticmethod
    def truncate_text(
        text: str,
        max_length: int,
        suffix: str = "...",
    ) -> str:
        """Truncate text to max length with suffix.

        If the text exceeds max_length, it is truncated and the suffix
        is appended. The total length including suffix will not exceed
        max_length.

        Args:
            text: The text to truncate.
            max_length: Maximum length of the result including suffix.
            suffix: The suffix to append when truncating.

        Returns:
            The truncated text with suffix, or original text if within limit.
        """
        if not text or len(text) <= max_length:
            return text

        # Ensure we have room for the suffix
        truncate_at = max_length - len(suffix)
        if truncate_at <= 0:
            return suffix[:max_length]

        return text[:truncate_at] + suffix
