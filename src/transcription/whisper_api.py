"""
OpenAI Whisper API transcription backend.

Implements the TranscriptionBackend interface using OpenAI's
Whisper API for cloud-based speech-to-text transcription.
"""

import asyncio
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI, APIError as OpenAIAPIError, RateLimitError as OpenAIRateLimitError
from openai import APITimeoutError, APIConnectionError, BadRequestError

from src.models.transcription import TranscriptionResult
from src.transcription.base import (
    TranscriptionBackend,
    TranscriptionError,
    InvalidAudioError,
    TranscriptionTimeoutError,
    RateLimitError,
    APIError,
    NetworkError,
)


class WhisperAPIBackend(TranscriptionBackend):
    """
    OpenAI Whisper API implementation.

    Uses the OpenAI Python SDK to call the Whisper API for
    transcription. Supports verbose_json response format for
    duration and segment information.
    """

    # Supported audio formats per OpenAI documentation
    SUPPORTED_FORMATS = [".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg", ".wav", ".webm"]

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        timeout: float = 120.0,
    ):
        """
        Initialize the Whisper API backend.

        Args:
            api_key: OpenAI API key for authentication.
            model: Whisper model name (default: "whisper-1").
            timeout: Request timeout in seconds (default: 120.0).
        """
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)

    @property
    def name(self) -> str:
        """Backend identifier."""
        return "whisper_api"

    def get_supported_formats(self) -> list[str]:
        """Return list of supported audio file extensions."""
        return self.SUPPORTED_FORMATS.copy()

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio file using OpenAI Whisper API.

        Args:
            audio_path: Path to the audio file to transcribe.
            language: Optional ISO-639-1 language code (e.g., "en").
                      If None, Whisper will auto-detect the language.

        Returns:
            TranscriptionResult with text, duration, language, and segments.

        Raises:
            FileNotFoundError: If audio file does not exist.
            InvalidAudioError: If audio format is not supported.
            TranscriptionTimeoutError: If the request times out.
            RateLimitError: If rate limited by the API.
            APIError: For server errors (5xx).
            NetworkError: For network connectivity issues.
            TranscriptionError: For other transcription failures.
        """
        # Validate file exists
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Validate format
        extension = audio_path.suffix.lower()
        if extension not in self.SUPPORTED_FORMATS:
            raise InvalidAudioError(
                f"Unsupported audio format: {extension}. "
                f"Supported formats: {self.SUPPORTED_FORMATS}"
            )

        try:
            # Open and transcribe the audio file
            with open(audio_path, "rb") as audio_file:
                # Build request parameters
                params = {
                    "model": self._model,
                    "file": audio_file,
                    "response_format": "verbose_json",  # Get duration and segments
                }

                # Add language if specified (otherwise auto-detect)
                if language:
                    params["language"] = language

                # Make API call
                response = await self._client.audio.transcriptions.create(**params)

            # Parse response into TranscriptionResult
            return self._parse_response(response)

        except APITimeoutError as e:
            raise TranscriptionTimeoutError(
                f"Whisper API request timed out after {self._timeout}s"
            ) from e

        except OpenAIRateLimitError as e:
            # Extract Retry-After header if available
            retry_after = self._extract_retry_after(e)
            raise RateLimitError(
                f"Rate limited by OpenAI API: {e.message}",
                retry_after=retry_after,
                original_error=e,
            ) from e

        except BadRequestError as e:
            # Bad request typically means invalid audio
            raise InvalidAudioError(
                f"Invalid audio file: {e.message}",
                original_error=e,
            ) from e

        except APIConnectionError as e:
            raise NetworkError(
                f"Network error connecting to OpenAI API: {str(e)}",
                original_error=e,
            ) from e

        except OpenAIAPIError as e:
            # Check for server errors (5xx)
            status_code = getattr(e, "status_code", None)
            if status_code and 500 <= status_code < 600:
                raise APIError(
                    f"OpenAI API server error: {e.message}",
                    status_code=status_code,
                    original_error=e,
                ) from e
            # Other API errors
            raise TranscriptionError(
                f"OpenAI API error: {e.message}",
                retryable=False,
                original_error=e,
            ) from e

        except Exception as e:
            # Catch-all for unexpected errors
            raise TranscriptionError(
                f"Unexpected transcription error: {str(e)}",
                retryable=False,
                original_error=e,
            ) from e

    def _parse_response(self, response) -> TranscriptionResult:
        """
        Parse Whisper API verbose_json response into TranscriptionResult.

        Args:
            response: The response object from OpenAI API.

        Returns:
            TranscriptionResult populated from the response.
        """
        # The response object has attributes for verbose_json format
        text = response.text or ""
        duration = getattr(response, "duration", 0.0) or 0.0
        language = getattr(response, "language", "unknown") or "unknown"

        # Parse segments if available
        segments = None
        if hasattr(response, "segments") and response.segments:
            segments = [
                {
                    "id": seg.id if hasattr(seg, "id") else i,
                    "start": getattr(seg, "start", 0.0),
                    "end": getattr(seg, "end", 0.0),
                    "text": getattr(seg, "text", ""),
                    "seek": getattr(seg, "seek", None),
                    "temperature": getattr(seg, "temperature", None),
                    "avg_logprob": getattr(seg, "avg_logprob", None),
                    "compression_ratio": getattr(seg, "compression_ratio", None),
                    "no_speech_prob": getattr(seg, "no_speech_prob", None),
                }
                for i, seg in enumerate(response.segments)
            ]

        return TranscriptionResult(
            text=text,
            duration_seconds=float(duration),
            language=language,
            segments=segments,
        )

    def _extract_retry_after(self, error: OpenAIRateLimitError) -> Optional[float]:
        """
        Extract Retry-After value from rate limit error.

        Args:
            error: The rate limit error from OpenAI.

        Returns:
            Seconds to wait before retrying, or None if not available.
        """
        # Try to get from response headers
        if hasattr(error, "response") and error.response:
            headers = getattr(error.response, "headers", {})
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after:
                try:
                    return float(retry_after)
                except (ValueError, TypeError):
                    pass
        return None
