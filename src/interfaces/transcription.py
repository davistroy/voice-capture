"""Interface for transcription services.

Defines the Protocol for transcription service implementations,
enabling loose coupling and easier testing per work item 6.8.
"""

from pathlib import Path
from typing import Optional, Protocol

from src.models.transcription import TranscriptionResult


class ITranscriptionService(Protocol):
    """Interface for transcription services.

    Implementations should provide transcription of audio files to text
    with automatic retry handling for transient failures.

    Example implementations:
        - TranscriptionService (Whisper API via OpenAI)
        - MockTranscriptionService (for testing)

    Usage:
        def process_audio(
            service: ITranscriptionService,
            file_path: Path
        ) -> TranscriptionResult:
            return await service.transcribe(file_path)
    """

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio file to text.

        Args:
            audio_path: Path to the audio file to transcribe.
            language: Optional ISO-639-1 language code (e.g., "en").
                     If None, language is auto-detected.

        Returns:
            TranscriptionResult with text, duration, language, and segments.

        Raises:
            FileNotFoundError: If audio file does not exist.
            InvalidAudioError: If audio format is invalid (no retry).
            TranscriptionError: After all retries exhausted.
        """
        ...
