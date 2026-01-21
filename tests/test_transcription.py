"""
Unit tests for the transcription service module.

Tests cover:
- TranscriptionBackend abstract interface
- WhisperAPIBackend with mocked OpenAI client
- TranscriptionService retry logic
- Error handling and classification
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from dataclasses import dataclass
from typing import Optional

import pytest

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
from src.transcription.whisper_api import WhisperAPIBackend
from src.transcription.service import (
    TranscriptionService,
    RetryConfig,
    create_whisper_service,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def whisper_success_response():
    """Load sample Whisper API success response from fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "api_responses" / "whisper_success.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def whisper_error_response():
    """Load sample Whisper API error response from fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "api_responses" / "whisper_error.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def mock_audio_file(temp_dir: Path, sample_audio_bytes: bytes) -> Path:
    """Create a mock audio file for testing."""
    audio_path = temp_dir / "test_audio.m4a"
    audio_path.write_bytes(sample_audio_bytes)
    return audio_path


@pytest.fixture
def mock_whisper_response():
    """Create a mock Whisper API response object."""
    @dataclass
    class MockSegment:
        id: int = 0
        start: float = 0.0
        end: float = 5.2
        text: str = "Test segment text"
        seek: int = 0
        temperature: float = 0.0
        avg_logprob: float = -0.25
        compression_ratio: float = 1.5
        no_speech_prob: float = 0.01

    @dataclass
    class MockResponse:
        text: str = "Test transcription text"
        language: str = "english"
        duration: float = 23.5
        segments: list = None

        def __post_init__(self):
            if self.segments is None:
                self.segments = [MockSegment()]

    return MockResponse


# =============================================================================
# TranscriptionBackend Abstract Interface Tests
# =============================================================================


class TestTranscriptionBackendInterface:
    """Tests for the abstract TranscriptionBackend interface."""

    def test_cannot_instantiate_abstract_class(self):
        """Verify TranscriptionBackend cannot be directly instantiated."""
        with pytest.raises(TypeError):
            TranscriptionBackend()

    def test_concrete_implementation_required_methods(self):
        """Verify concrete implementations must implement all methods."""
        class IncompleteBackend(TranscriptionBackend):
            pass

        with pytest.raises(TypeError):
            IncompleteBackend()

    def test_complete_implementation_works(self):
        """Verify a complete implementation can be instantiated."""
        class CompleteBackend(TranscriptionBackend):
            async def transcribe(self, audio_path: Path, language: Optional[str] = None):
                return TranscriptionResult("test", 1.0, "en")

            def get_supported_formats(self):
                return [".wav"]

            @property
            def name(self):
                return "test"

        backend = CompleteBackend()
        assert backend.name == "test"
        assert backend.get_supported_formats() == [".wav"]


# =============================================================================
# Error Class Tests
# =============================================================================


class TestTranscriptionErrors:
    """Tests for transcription error classes."""

    def test_transcription_error_default_retryable(self):
        """Verify TranscriptionError is retryable by default."""
        error = TranscriptionError("Test error")
        assert error.retryable is True
        assert error.message == "Test error"
        assert error.original_error is None

    def test_transcription_error_non_retryable(self):
        """Verify TranscriptionError can be marked non-retryable."""
        error = TranscriptionError("Test error", retryable=False)
        assert error.retryable is False

    def test_invalid_audio_error_not_retryable(self):
        """Verify InvalidAudioError is never retryable."""
        error = InvalidAudioError("Invalid format")
        assert error.retryable is False

    def test_timeout_error_is_retryable(self):
        """Verify TranscriptionTimeoutError is retryable."""
        error = TranscriptionTimeoutError()
        assert error.retryable is True
        assert "timed out" in error.message

    def test_rate_limit_error_with_retry_after(self):
        """Verify RateLimitError stores retry_after value."""
        error = RateLimitError("Rate limited", retry_after=30.0)
        assert error.retryable is True
        assert error.retry_after == 30.0

    def test_api_error_with_status_code(self):
        """Verify APIError stores status code."""
        error = APIError("Server error", status_code=503)
        assert error.retryable is True
        assert error.status_code == 503

    def test_network_error_is_retryable(self):
        """Verify NetworkError is retryable."""
        error = NetworkError("Connection failed")
        assert error.retryable is True


# =============================================================================
# RetryConfig Tests
# =============================================================================


class TestRetryConfig:
    """Tests for RetryConfig exponential backoff calculation."""

    def test_default_config_values(self):
        """Verify default retry configuration."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_backoff_seconds == 5.0
        assert config.max_backoff_seconds == 300.0
        assert config.backoff_multiplier == 2.0
        assert config.jitter_factor == 0.1

    def test_exponential_backoff_without_jitter(self):
        """Verify exponential backoff calculation (ignoring jitter)."""
        config = RetryConfig(base_backoff_seconds=5.0, backoff_multiplier=2.0, jitter_factor=0.0)

        # retry 0: 5 * 2^0 = 5
        assert config.get_backoff(0) == 5.0
        # retry 1: 5 * 2^1 = 10
        assert config.get_backoff(1) == 10.0
        # retry 2: 5 * 2^2 = 20
        assert config.get_backoff(2) == 20.0

    def test_backoff_respects_max_limit(self):
        """Verify backoff is capped at max_backoff_seconds."""
        config = RetryConfig(
            base_backoff_seconds=100.0,
            max_backoff_seconds=300.0,
            backoff_multiplier=2.0,
            jitter_factor=0.0,
        )

        # retry 2: 100 * 2^2 = 400, but capped at 300
        assert config.get_backoff(2) == 300.0

    def test_backoff_includes_jitter(self):
        """Verify backoff includes random jitter."""
        config = RetryConfig(
            base_backoff_seconds=10.0,
            jitter_factor=0.1,
        )

        # With 10% jitter on 10s base, should be between 10 and 11
        values = [config.get_backoff(0) for _ in range(100)]
        assert all(10.0 <= v <= 11.0 for v in values)
        # Should have some variation (not all exactly the same)
        assert len(set(values)) > 1


# =============================================================================
# WhisperAPIBackend Tests
# =============================================================================


class TestWhisperAPIBackend:
    """Tests for WhisperAPIBackend implementation."""

    def test_name_property(self):
        """Verify backend name is 'whisper_api'."""
        backend = WhisperAPIBackend(api_key="test-key")
        assert backend.name == "whisper_api"

    def test_supported_formats(self):
        """Verify supported audio formats."""
        backend = WhisperAPIBackend(api_key="test-key")
        formats = backend.get_supported_formats()

        assert ".m4a" in formats
        assert ".mp3" in formats
        assert ".wav" in formats
        assert ".flac" in formats

    @pytest.mark.asyncio
    async def test_transcribe_file_not_found(self, temp_dir: Path):
        """Verify FileNotFoundError for missing files."""
        backend = WhisperAPIBackend(api_key="test-key")
        missing_file = temp_dir / "nonexistent.m4a"

        with pytest.raises(FileNotFoundError):
            await backend.transcribe(missing_file)

    @pytest.mark.asyncio
    async def test_transcribe_unsupported_format(self, temp_dir: Path):
        """Verify InvalidAudioError for unsupported formats."""
        backend = WhisperAPIBackend(api_key="test-key")
        invalid_file = temp_dir / "test.xyz"
        invalid_file.write_text("not audio")

        with pytest.raises(InvalidAudioError) as exc_info:
            await backend.transcribe(invalid_file)

        assert ".xyz" in str(exc_info.value)
        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_transcribe_success(self, mock_audio_file: Path, mock_whisper_response):
        """Verify successful transcription with mocked API."""
        backend = WhisperAPIBackend(api_key="test-key")

        # Mock the OpenAI client
        mock_response = mock_whisper_response()
        backend._client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        result = await backend.transcribe(mock_audio_file)

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Test transcription text"
        assert result.duration_seconds == 23.5
        assert result.language == "english"
        assert result.segments is not None
        assert len(result.segments) == 1

    @pytest.mark.asyncio
    async def test_transcribe_with_language(self, mock_audio_file: Path, mock_whisper_response):
        """Verify language parameter is passed to API."""
        backend = WhisperAPIBackend(api_key="test-key")
        mock_response = mock_whisper_response()
        mock_create = AsyncMock(return_value=mock_response)
        backend._client.audio.transcriptions.create = mock_create

        await backend.transcribe(mock_audio_file, language="en")

        # Verify language was passed
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs.get("language") == "en"

    @pytest.mark.asyncio
    async def test_transcribe_timeout_error(self, mock_audio_file: Path):
        """Verify timeout handling."""
        from openai import APITimeoutError

        backend = WhisperAPIBackend(api_key="test-key", timeout=30.0)

        # Mock timeout
        backend._client.audio.transcriptions.create = AsyncMock(
            side_effect=APITimeoutError(request=MagicMock())
        )

        with pytest.raises(TranscriptionTimeoutError):
            await backend.transcribe(mock_audio_file)

    @pytest.mark.asyncio
    async def test_transcribe_rate_limit_error(self, mock_audio_file: Path):
        """Verify rate limit handling."""
        from openai import RateLimitError as OpenAIRateLimitError

        backend = WhisperAPIBackend(api_key="test-key")

        # Create mock rate limit error with Retry-After header
        mock_response = MagicMock()
        mock_response.headers = {"Retry-After": "60"}
        mock_error = OpenAIRateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body=None,
        )

        backend._client.audio.transcriptions.create = AsyncMock(side_effect=mock_error)

        with pytest.raises(RateLimitError) as exc_info:
            await backend.transcribe(mock_audio_file)

        assert exc_info.value.retryable is True
        assert exc_info.value.retry_after == 60.0

    @pytest.mark.asyncio
    async def test_transcribe_bad_request_error(self, mock_audio_file: Path):
        """Verify bad request handling (invalid audio)."""
        from openai import BadRequestError

        backend = WhisperAPIBackend(api_key="test-key")

        mock_error = BadRequestError(
            message="Invalid file format",
            response=MagicMock(),
            body=None,
        )

        backend._client.audio.transcriptions.create = AsyncMock(side_effect=mock_error)

        with pytest.raises(InvalidAudioError) as exc_info:
            await backend.transcribe(mock_audio_file)

        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_transcribe_server_error(self, mock_audio_file: Path):
        """Verify server error handling (5xx)."""
        from openai import APIError as OpenAIAPIError

        backend = WhisperAPIBackend(api_key="test-key")

        mock_error = OpenAIAPIError(
            message="Internal server error",
            request=MagicMock(),
            body=None,
        )
        mock_error.status_code = 503

        backend._client.audio.transcriptions.create = AsyncMock(side_effect=mock_error)

        with pytest.raises(APIError) as exc_info:
            await backend.transcribe(mock_audio_file)

        assert exc_info.value.retryable is True
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_transcribe_network_error(self, mock_audio_file: Path):
        """Verify network error handling."""
        from openai import APIConnectionError

        backend = WhisperAPIBackend(api_key="test-key")

        backend._client.audio.transcriptions.create = AsyncMock(
            side_effect=APIConnectionError(request=MagicMock())
        )

        with pytest.raises(NetworkError):
            await backend.transcribe(mock_audio_file)


# =============================================================================
# TranscriptionService Tests
# =============================================================================


class TestTranscriptionService:
    """Tests for TranscriptionService facade."""

    @pytest.fixture
    def mock_backend(self):
        """Create a mock transcription backend."""
        backend = MagicMock(spec=TranscriptionBackend)
        backend.name = "mock_backend"
        backend.get_supported_formats.return_value = [".m4a", ".wav"]
        return backend

    def test_backend_name_property(self, mock_backend):
        """Verify backend name is exposed."""
        service = TranscriptionService(backend=mock_backend)
        assert service.backend_name == "mock_backend"

    def test_supported_formats_property(self, mock_backend):
        """Verify supported formats are exposed."""
        service = TranscriptionService(backend=mock_backend)
        assert service.supported_formats == [".m4a", ".wav"]

    @pytest.mark.asyncio
    async def test_transcribe_file_not_found(self, mock_backend, temp_dir: Path):
        """Verify FileNotFoundError for missing files (before calling backend)."""
        service = TranscriptionService(backend=mock_backend)
        missing_file = temp_dir / "nonexistent.m4a"

        with pytest.raises(FileNotFoundError):
            await service.transcribe(missing_file)

        # Backend should not be called
        mock_backend.transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_transcribe_success_first_attempt(self, mock_backend, mock_audio_file: Path):
        """Verify successful transcription on first attempt."""
        expected_result = TranscriptionResult(
            text="Test transcription",
            duration_seconds=10.0,
            language="en",
        )
        mock_backend.transcribe = AsyncMock(return_value=expected_result)

        service = TranscriptionService(backend=mock_backend)
        result = await service.transcribe(mock_audio_file)

        assert result == expected_result
        assert mock_backend.transcribe.call_count == 1

    @pytest.mark.asyncio
    async def test_transcribe_invalid_audio_no_retry(self, mock_backend, mock_audio_file: Path):
        """Verify InvalidAudioError is not retried."""
        mock_backend.transcribe = AsyncMock(
            side_effect=InvalidAudioError("Invalid format")
        )

        service = TranscriptionService(
            backend=mock_backend,
            retry_config=RetryConfig(max_retries=3),
        )

        with pytest.raises(InvalidAudioError):
            await service.transcribe(mock_audio_file)

        # Should only attempt once
        assert mock_backend.transcribe.call_count == 1

    @pytest.mark.asyncio
    async def test_transcribe_retry_on_timeout(self, mock_backend, mock_audio_file: Path):
        """Verify timeout errors trigger retry."""
        expected_result = TranscriptionResult(
            text="Test",
            duration_seconds=5.0,
            language="en",
        )
        mock_backend.transcribe = AsyncMock(
            side_effect=[
                TranscriptionTimeoutError("Timeout"),
                expected_result,
            ]
        )

        # Use very short backoff for test speed
        service = TranscriptionService(
            backend=mock_backend,
            retry_config=RetryConfig(base_backoff_seconds=0.01),
        )

        result = await service.transcribe(mock_audio_file)

        assert result == expected_result
        assert mock_backend.transcribe.call_count == 2

    @pytest.mark.asyncio
    async def test_transcribe_retry_on_api_error(self, mock_backend, mock_audio_file: Path):
        """Verify API errors trigger retry."""
        expected_result = TranscriptionResult(
            text="Test",
            duration_seconds=5.0,
            language="en",
        )
        mock_backend.transcribe = AsyncMock(
            side_effect=[
                APIError("Server error", status_code=503),
                APIError("Server error", status_code=500),
                expected_result,
            ]
        )

        service = TranscriptionService(
            backend=mock_backend,
            retry_config=RetryConfig(max_retries=3, base_backoff_seconds=0.01),
        )

        result = await service.transcribe(mock_audio_file)

        assert result == expected_result
        assert mock_backend.transcribe.call_count == 3

    @pytest.mark.asyncio
    async def test_transcribe_retry_on_network_error(self, mock_backend, mock_audio_file: Path):
        """Verify network errors trigger retry."""
        expected_result = TranscriptionResult(
            text="Test",
            duration_seconds=5.0,
            language="en",
        )
        mock_backend.transcribe = AsyncMock(
            side_effect=[
                NetworkError("Connection failed"),
                expected_result,
            ]
        )

        service = TranscriptionService(
            backend=mock_backend,
            retry_config=RetryConfig(base_backoff_seconds=0.01),
        )

        result = await service.transcribe(mock_audio_file)

        assert result == expected_result
        assert mock_backend.transcribe.call_count == 2

    @pytest.mark.asyncio
    async def test_transcribe_respects_retry_after_header(self, mock_backend, mock_audio_file: Path):
        """Verify Retry-After header is respected for rate limits."""
        expected_result = TranscriptionResult(
            text="Test",
            duration_seconds=5.0,
            language="en",
        )

        mock_backend.transcribe = AsyncMock(
            side_effect=[
                RateLimitError("Rate limited", retry_after=0.05),
                expected_result,
            ]
        )

        service = TranscriptionService(
            backend=mock_backend,
            retry_config=RetryConfig(base_backoff_seconds=10.0),  # Long default
        )

        # Time the operation
        import time
        start = time.time()
        result = await service.transcribe(mock_audio_file)
        elapsed = time.time() - start

        assert result == expected_result
        # Should wait ~0.05s, not 10s
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_transcribe_exhausts_retries(self, mock_backend, mock_audio_file: Path):
        """Verify error raised after exhausting all retries."""
        mock_backend.transcribe = AsyncMock(
            side_effect=TranscriptionTimeoutError("Timeout")
        )

        service = TranscriptionService(
            backend=mock_backend,
            retry_config=RetryConfig(max_retries=2, base_backoff_seconds=0.01),
        )

        with pytest.raises(TranscriptionTimeoutError):
            await service.transcribe(mock_audio_file)

        # Initial attempt + 2 retries = 3 total
        assert mock_backend.transcribe.call_count == 3

    @pytest.mark.asyncio
    async def test_transcribe_with_retry_alias(self, mock_backend, mock_audio_file: Path):
        """Verify transcribe_with_retry is an alias for transcribe."""
        expected_result = TranscriptionResult(
            text="Test",
            duration_seconds=5.0,
            language="en",
        )
        mock_backend.transcribe = AsyncMock(return_value=expected_result)

        service = TranscriptionService(backend=mock_backend)
        result = await service.transcribe_with_retry(mock_audio_file)

        assert result == expected_result

    @pytest.mark.asyncio
    async def test_non_retryable_error_fails_immediately(self, mock_backend, mock_audio_file: Path):
        """Verify non-retryable errors fail without retry."""
        mock_backend.transcribe = AsyncMock(
            side_effect=TranscriptionError("Fatal error", retryable=False)
        )

        service = TranscriptionService(
            backend=mock_backend,
            retry_config=RetryConfig(max_retries=3),
        )

        with pytest.raises(TranscriptionError):
            await service.transcribe(mock_audio_file)

        # Should only attempt once
        assert mock_backend.transcribe.call_count == 1


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateWhisperService:
    """Tests for the create_whisper_service factory function."""

    def test_creates_service_with_defaults(self):
        """Verify factory creates service with default settings."""
        service = create_whisper_service(api_key="test-key")

        assert isinstance(service, TranscriptionService)
        assert service.backend_name == "whisper_api"
        assert ".m4a" in service.supported_formats

    def test_creates_service_with_custom_config(self):
        """Verify factory accepts custom configuration."""
        service = create_whisper_service(
            api_key="test-key",
            model="whisper-1",
            timeout=60.0,
            max_retries=5,
            base_backoff=10.0,
        )

        assert isinstance(service, TranscriptionService)
        assert service._retry_config.max_retries == 5
        assert service._retry_config.base_backoff_seconds == 10.0


# =============================================================================
# Integration-style Tests with Fixtures
# =============================================================================


class TestTranscriptionWithFixtures:
    """Tests using fixture files for realistic responses."""

    @pytest.mark.asyncio
    async def test_parse_whisper_success_fixture(
        self,
        mock_audio_file: Path,
        whisper_success_response: dict,
    ):
        """Verify parsing of real Whisper API success response."""
        # Convert fixture to mock response object
        @dataclass
        class MockSegment:
            id: int
            start: float
            end: float
            text: str
            seek: int
            temperature: float
            avg_logprob: float
            compression_ratio: float
            no_speech_prob: float
            tokens: list = None  # Optional field present in real responses

        @dataclass
        class MockResponse:
            text: str
            language: str
            duration: float
            task: str
            segments: list

        segments = [
            MockSegment(**seg) for seg in whisper_success_response["segments"]
        ]
        mock_response = MockResponse(
            text=whisper_success_response["text"],
            language=whisper_success_response["language"],
            duration=whisper_success_response["duration"],
            task=whisper_success_response["task"],
            segments=segments,
        )

        backend = WhisperAPIBackend(api_key="test-key")
        backend._client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        result = await backend.transcribe(mock_audio_file)

        assert result.text == whisper_success_response["text"]
        assert result.duration_seconds == whisper_success_response["duration"]
        assert result.language == whisper_success_response["language"]
        assert len(result.segments) == len(whisper_success_response["segments"])

    def test_transcription_result_from_whisper_response(self, whisper_success_response: dict):
        """Verify TranscriptionResult.from_whisper_response parsing."""
        result = TranscriptionResult.from_whisper_response(whisper_success_response)

        assert result.text == whisper_success_response["text"]
        assert result.duration_seconds == whisper_success_response["duration"]
        assert result.language == whisper_success_response["language"]
        assert len(result.segments) == len(whisper_success_response["segments"])
