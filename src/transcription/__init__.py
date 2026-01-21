"""
Transcription service module.

Provides speech-to-text transcription capabilities with support
for multiple backends (OpenAI Whisper API, local Whisper).

Main components:
- TranscriptionBackend: Abstract interface for transcription implementations
- WhisperAPIBackend: OpenAI Whisper API implementation
- TranscriptionService: High-level facade with retry logic
- Error classes: Typed exceptions for error handling

Example usage:
    ```python
    from src.transcription import create_whisper_service, TranscriptionError

    # Create service
    service = create_whisper_service(api_key="sk-...")

    # Transcribe audio
    try:
        result = await service.transcribe(Path("audio.m4a"))
        print(f"Text: {result.text}")
        print(f"Duration: {result.duration_seconds}s")
    except TranscriptionError as e:
        print(f"Transcription failed: {e}")
    ```
"""

from src.transcription.base import (
    TranscriptionBackend,
    TranscriptionError,
    InvalidAudioError,
    TranscriptionTimeoutError,
    RateLimitError,
    APIError,
    NetworkError,
)
from src.transcription.whisper_api import WhisperAPIBackend
from src.transcription.service import (
    TranscriptionService,
    RetryConfig,
    create_whisper_service,
)

__all__ = [
    # Abstract base
    "TranscriptionBackend",
    # Implementations
    "WhisperAPIBackend",
    # Service
    "TranscriptionService",
    "RetryConfig",
    "create_whisper_service",
    # Errors
    "TranscriptionError",
    "InvalidAudioError",
    "TranscriptionTimeoutError",
    "RateLimitError",
    "APIError",
    "NetworkError",
]
