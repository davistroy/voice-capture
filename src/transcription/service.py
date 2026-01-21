"""
Transcription service facade with retry logic.

Provides a high-level interface for transcription with automatic
retry handling, exponential backoff, and error classification.
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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

logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    """Configuration for retry behavior with exponential backoff."""

    max_retries: int = 3
    base_backoff_seconds: float = 5.0
    max_backoff_seconds: float = 300.0  # 5 minutes
    backoff_multiplier: float = 2.0
    jitter_factor: float = 0.1  # 10% jitter

    def get_backoff(self, retry_count: int) -> float:
        """
        Calculate exponential backoff with jitter.

        Args:
            retry_count: Current retry attempt (0-based).

        Returns:
            Seconds to wait before retrying.
        """
        # Calculate base exponential backoff
        backoff = min(
            self.base_backoff_seconds * (self.backoff_multiplier ** retry_count),
            self.max_backoff_seconds,
        )

        # Add jitter (random value between 0 and jitter_factor * backoff)
        jitter = backoff * self.jitter_factor * random.random()

        return backoff + jitter


class TranscriptionService:
    """
    Facade for transcription operations with retry logic.

    Wraps a TranscriptionBackend and adds automatic retry handling
    with exponential backoff for transient failures.
    """

    def __init__(
        self,
        backend: TranscriptionBackend,
        retry_config: Optional[RetryConfig] = None,
    ):
        """
        Initialize the transcription service.

        Args:
            backend: The transcription backend to use.
            retry_config: Optional retry configuration. If None, uses defaults.
        """
        self._backend = backend
        self._retry_config = retry_config or RetryConfig()

    @property
    def backend_name(self) -> str:
        """Get the name of the underlying backend."""
        return self._backend.name

    @property
    def supported_formats(self) -> list[str]:
        """Get supported audio formats from the backend."""
        return self._backend.get_supported_formats()

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio file with automatic retry on transient failures.

        Args:
            audio_path: Path to the audio file to transcribe.
            language: Optional ISO-639-1 language code (e.g., "en").

        Returns:
            TranscriptionResult with text, duration, language, and segments.

        Raises:
            FileNotFoundError: If audio file does not exist.
            InvalidAudioError: If audio format is invalid (no retry).
            TranscriptionError: After all retries exhausted.
        """
        # Validate file exists upfront
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        last_error: Optional[Exception] = None
        attempts = 0

        while attempts <= self._retry_config.max_retries:
            try:
                logger.debug(
                    "Transcription attempt %d/%d for %s",
                    attempts + 1,
                    self._retry_config.max_retries + 1,
                    audio_path.name,
                )

                result = await self._backend.transcribe(audio_path, language)

                logger.info(
                    "Transcription successful for %s: %.1fs, language=%s",
                    audio_path.name,
                    result.duration_seconds,
                    result.language,
                )

                return result

            except InvalidAudioError:
                # Invalid audio files should not be retried
                logger.warning(
                    "Invalid audio file, not retrying: %s",
                    audio_path.name,
                )
                raise

            except RateLimitError as e:
                # Rate limit - use Retry-After if available
                last_error = e
                attempts += 1

                if attempts > self._retry_config.max_retries:
                    break

                # Use Retry-After header if available, otherwise use backoff
                if e.retry_after:
                    wait_time = e.retry_after
                    logger.warning(
                        "Rate limited, waiting %.1fs (Retry-After header): %s",
                        wait_time,
                        audio_path.name,
                    )
                else:
                    wait_time = self._retry_config.get_backoff(attempts - 1)
                    logger.warning(
                        "Rate limited, waiting %.1fs (backoff): %s",
                        wait_time,
                        audio_path.name,
                    )

                await asyncio.sleep(wait_time)

            except (TranscriptionTimeoutError, APIError, NetworkError) as e:
                # Transient errors - retry with backoff
                last_error = e
                attempts += 1

                if attempts > self._retry_config.max_retries:
                    break

                wait_time = self._retry_config.get_backoff(attempts - 1)
                logger.warning(
                    "Transcription failed (attempt %d/%d), retrying in %.1fs: %s - %s",
                    attempts,
                    self._retry_config.max_retries + 1,
                    wait_time,
                    type(e).__name__,
                    str(e),
                )

                await asyncio.sleep(wait_time)

            except TranscriptionError as e:
                # Non-retryable transcription error
                if not e.retryable:
                    logger.error(
                        "Non-retryable transcription error for %s: %s",
                        audio_path.name,
                        str(e),
                    )
                    raise

                # Retryable error
                last_error = e
                attempts += 1

                if attempts > self._retry_config.max_retries:
                    break

                wait_time = self._retry_config.get_backoff(attempts - 1)
                logger.warning(
                    "Transcription error (attempt %d/%d), retrying in %.1fs: %s",
                    attempts,
                    self._retry_config.max_retries + 1,
                    wait_time,
                    str(e),
                )

                await asyncio.sleep(wait_time)

            except Exception as e:
                # Unexpected error - log and don't retry
                logger.error(
                    "Unexpected error during transcription of %s: %s",
                    audio_path.name,
                    str(e),
                    exc_info=True,
                )
                raise TranscriptionError(
                    f"Unexpected transcription error: {str(e)}",
                    retryable=False,
                    original_error=e,
                ) from e

        # All retries exhausted
        logger.error(
            "Transcription failed after %d attempts for %s: %s",
            attempts,
            audio_path.name,
            str(last_error),
        )

        if last_error:
            if isinstance(last_error, TranscriptionError):
                raise last_error
            raise TranscriptionError(
                f"Transcription failed after {attempts} attempts: {str(last_error)}",
                retryable=False,
                original_error=last_error,
            ) from last_error

        raise TranscriptionError(
            f"Transcription failed after {attempts} attempts",
            retryable=False,
        )

    async def transcribe_with_retry(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Alias for transcribe() - kept for API compatibility.

        Args:
            audio_path: Path to the audio file to transcribe.
            language: Optional ISO-639-1 language code.

        Returns:
            TranscriptionResult with text, duration, language, and segments.
        """
        return await self.transcribe(audio_path, language)


def create_whisper_service(
    api_key: str,
    model: str = "whisper-1",
    timeout: float = 120.0,
    max_retries: int = 3,
    base_backoff: float = 5.0,
) -> TranscriptionService:
    """
    Factory function to create a TranscriptionService with Whisper API backend.

    Args:
        api_key: OpenAI API key.
        model: Whisper model name (default: "whisper-1").
        timeout: Request timeout in seconds (default: 120.0).
        max_retries: Maximum retry attempts (default: 3).
        base_backoff: Base backoff delay in seconds (default: 5.0).

    Returns:
        Configured TranscriptionService instance.
    """
    from src.transcription.whisper_api import WhisperAPIBackend

    backend = WhisperAPIBackend(
        api_key=api_key,
        model=model,
        timeout=timeout,
    )

    retry_config = RetryConfig(
        max_retries=max_retries,
        base_backoff_seconds=base_backoff,
    )

    return TranscriptionService(backend=backend, retry_config=retry_config)
