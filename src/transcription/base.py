"""
Abstract base class for transcription backends.

Defines the interface for all transcription implementations,
allowing for swappable backends (e.g., Whisper API, local Whisper).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.models.transcription import TranscriptionResult


class TranscriptionBackend(ABC):
    """
    Abstract interface for transcription backends.

    All transcription implementations must inherit from this class
    and implement the required methods. This enables the Strategy
    pattern for swapping between API-based and local transcription.
    """

    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file to text.

        Args:
            audio_path: Path to the audio file to transcribe.
            language: Optional ISO-639-1 language code (e.g., "en").
                      If None, the backend should auto-detect.

        Returns:
            TranscriptionResult with text, duration, language, and segments.

        Raises:
            TranscriptionError: If transcription fails.
            FileNotFoundError: If audio file does not exist.
        """
        ...

    @abstractmethod
    def get_supported_formats(self) -> list[str]:
        """
        Return list of supported audio file extensions.

        Returns:
            List of extensions including the dot (e.g., [".m4a", ".wav"]).
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Backend identifier string.

        Returns:
            Human-readable name for logging and configuration.
        """
        ...


class TranscriptionError(Exception):
    """Base exception for transcription failures."""

    def __init__(
        self,
        message: str,
        retryable: bool = True,
        original_error: Optional[Exception] = None,
    ):
        """
        Initialize transcription error.

        Args:
            message: Human-readable error description.
            retryable: Whether this error should trigger a retry.
            original_error: The underlying exception, if any.
        """
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.original_error = original_error


class InvalidAudioError(TranscriptionError):
    """Raised when the audio file format is invalid or unsupported."""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message, retryable=False, original_error=original_error)


class TranscriptionTimeoutError(TranscriptionError):
    """Raised when transcription times out."""

    def __init__(self, message: str = "Transcription timed out"):
        super().__init__(message, retryable=True)


class RateLimitError(TranscriptionError):
    """Raised when rate limited by the API."""

    def __init__(
        self,
        message: str,
        retry_after: Optional[float] = None,
        original_error: Optional[Exception] = None,
    ):
        """
        Initialize rate limit error.

        Args:
            message: Human-readable error description.
            retry_after: Seconds to wait before retrying, from Retry-After header.
            original_error: The underlying exception, if any.
        """
        super().__init__(message, retryable=True, original_error=original_error)
        self.retry_after = retry_after


class APIError(TranscriptionError):
    """Raised for API server errors (5xx)."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message, retryable=True, original_error=original_error)
        self.status_code = status_code


class NetworkError(TranscriptionError):
    """Raised for network connectivity issues."""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message, retryable=True, original_error=original_error)
