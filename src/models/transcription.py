"""
Transcription result model.

Contains the TranscriptionResult dataclass representing output from
the transcription service (OpenAI Whisper API).
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import json


@dataclass
class TranscriptionResult:
    """
    Result from transcription service.

    Attributes:
        text: The full transcribed text content.
        duration_seconds: Audio duration in seconds.
        language: Detected or specified language code (e.g., "en").
        segments: Optional list of timestamped segments with start/end times.
                  Each segment is a dict with keys like 'start', 'end', 'text'.
    """
    text: str
    duration_seconds: float
    language: str
    segments: Optional[List[Dict[str, Any]]] = None

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")
        if not isinstance(self.duration_seconds, (int, float)):
            raise ValueError("duration_seconds must be a number")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds cannot be negative")
        if not isinstance(self.language, str):
            raise ValueError("language must be a string")
        if self.segments is not None and not isinstance(self.segments, list):
            raise ValueError("segments must be a list or None")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation suitable for database storage.
        """
        return asdict(self)

    def to_json(self) -> str:
        """
        Serialize to JSON string.

        Returns:
            JSON string representation.
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranscriptionResult":
        """
        Create instance from dictionary.

        Args:
            data: Dictionary with transcription result fields.

        Returns:
            New TranscriptionResult instance.

        Raises:
            KeyError: If required fields are missing.
            ValueError: If field types are invalid.
        """
        return cls(
            text=data["text"],
            duration_seconds=float(data["duration_seconds"]),
            language=data["language"],
            segments=data.get("segments"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "TranscriptionResult":
        """
        Deserialize from JSON string.

        Args:
            json_str: JSON string representation.

        Returns:
            New TranscriptionResult instance.
        """
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_whisper_response(cls, response: Dict[str, Any]) -> "TranscriptionResult":
        """
        Create instance from OpenAI Whisper API verbose_json response.

        Args:
            response: Raw response from Whisper API with verbose_json format.

        Returns:
            New TranscriptionResult instance.
        """
        return cls(
            text=response["text"],
            duration_seconds=float(response.get("duration", 0)),
            language=response.get("language", "unknown"),
            segments=response.get("segments"),
        )

    def get_word_count(self) -> int:
        """
        Get approximate word count from transcript.

        Returns:
            Number of words in the transcript.
        """
        return len(self.text.split())

    def get_first_sentence(self, max_words: int = 20) -> str:
        """
        Extract first sentence for title generation.

        Args:
            max_words: Maximum number of words to include.

        Returns:
            First sentence or truncated text.
        """
        # Split on sentence-ending punctuation
        text = self.text.strip()
        for delimiter in [". ", "! ", "? ", "\n"]:
            if delimiter in text:
                first = text.split(delimiter)[0] + delimiter[0]
                break
        else:
            first = text

        # Truncate if too long
        words = first.split()
        if len(words) > max_words:
            return " ".join(words[:max_words]) + "..."
        return first
