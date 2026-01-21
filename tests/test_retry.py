"""
Comprehensive tests for retry logic hardening (Work Item 3.3).

Tests cover:
- Error categorization (retryable vs non-retryable)
- Circuit breaker pattern (closed, open, half-open states)
- Retry backoff calculations with jitter
- State preservation on retry (transcript/classification not lost)
- Improved error logging in failure_log
- Integration with orchestrator error handling
"""

import asyncio
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import CaptureRow
from src.models.transcription import TranscriptionResult
from src.notion.client import NotionPage, NotionError, NotionRateLimitError
from src.pipeline.retry import (
    RetryConfig,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
    CircuitOpenError,
    ErrorCategory,
    ErrorClassification,
    classify_error,
    build_detailed_error_log,
    RETRYABLE_ERROR_TYPES,
    NON_RETRYABLE_ERROR_TYPES,
    PIPELINE_RETRY_CONFIG,
    TRANSCRIPTION_RETRY_CONFIG,
    CLASSIFICATION_RETRY_CONFIG,
    NOTION_RETRY_CONFIG,
)
from src.pipeline.orchestrator import (
    PipelineOrchestrator,
    ProcessingResult,
    ProcessingStage,
)
from src.transcription.base import (
    TranscriptionError,
    InvalidAudioError,
    TranscriptionTimeoutError,
    RateLimitError,
    APIError,
    NetworkError,
)


# =============================================================================
# Error Categorization Tests
# =============================================================================


class TestErrorCategorization:
    """Tests for error classification logic."""

    def test_retryable_error_with_explicit_attribute(self):
        """Verify errors with retryable=True are classified as retryable."""
        error = TranscriptionError("Connection timeout", retryable=True)
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RETRYABLE
        assert classification.error_type == "TranscriptionError"
        assert "Connection timeout" in classification.message

    def test_non_retryable_error_with_explicit_attribute(self):
        """Verify errors with retryable=False are classified as non-retryable."""
        error = InvalidAudioError("Invalid format")
        classification = classify_error(error)

        assert classification.category == ErrorCategory.NON_RETRYABLE
        assert classification.error_type == "InvalidAudioError"

    def test_timeout_error_is_retryable(self):
        """Verify timeout errors are retryable."""
        error = TranscriptionTimeoutError()
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RETRYABLE
        assert classification.error_type == "TranscriptionTimeoutError"

    def test_rate_limit_error_includes_retry_after(self):
        """Verify rate limit errors include retry_after hint."""
        error = RateLimitError("Rate limited", retry_after=30.0)
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RETRYABLE
        assert classification.retry_after == 30.0
        assert "retry_after_hint" in (classification.details or {})

    def test_api_error_is_retryable(self):
        """Verify API errors (5xx) are retryable."""
        error = APIError("Internal server error", status_code=500)
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RETRYABLE
        assert classification.details.get("status_code") == 500

    def test_network_error_is_retryable(self):
        """Verify network errors are retryable."""
        error = NetworkError("Connection refused")
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RETRYABLE
        assert classification.error_type == "NetworkError"

    def test_notion_error_is_retryable(self):
        """Verify Notion errors are retryable."""
        error = NotionError("Server error")
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RETRYABLE
        assert classification.error_type == "NotionError"

    def test_notion_rate_limit_is_retryable(self):
        """Verify Notion rate limit errors are retryable."""
        error = NotionRateLimitError("Rate limited", retry_after=5.0)
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RETRYABLE
        # Note: NotionRateLimitError doesn't have retryable attribute,
        # but is in RETRYABLE_ERROR_TYPES

    def test_file_not_found_is_non_retryable(self):
        """Verify FileNotFoundError is non-retryable."""
        error = FileNotFoundError("Audio file missing")
        classification = classify_error(error)

        assert classification.category == ErrorCategory.NON_RETRYABLE
        assert classification.error_type == "FileNotFoundError"

    def test_value_error_is_non_retryable(self):
        """Verify ValueError is non-retryable."""
        error = ValueError("Invalid input")
        classification = classify_error(error)

        assert classification.category == ErrorCategory.NON_RETRYABLE
        assert classification.error_type == "ValueError"

    def test_unknown_error_defaults_to_retryable(self):
        """Verify unknown error types default to retryable (fail-safe)."""

        class CustomUnknownError(Exception):
            pass

        error = CustomUnknownError("Something unexpected")
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RETRYABLE
        assert classification.details.get("unknown_error_type") is True

    def test_4xx_status_code_is_non_retryable(self):
        """Verify 4xx status codes (except 429) are non-retryable."""

        class HTTPError(Exception):
            def __init__(self, message, status_code):
                super().__init__(message)
                self.status_code = status_code

        error = HTTPError("Bad request", status_code=400)
        classification = classify_error(error)

        assert classification.category == ErrorCategory.NON_RETRYABLE
        assert classification.details.get("status_code") == 400

    def test_429_status_code_is_retryable(self):
        """Verify 429 rate limit status code is retryable."""

        class HTTPError(Exception):
            def __init__(self, message, status_code):
                super().__init__(message)
                self.status_code = status_code

        error = HTTPError("Too many requests", status_code=429)
        classification = classify_error(error)

        assert classification.category == ErrorCategory.RETRYABLE
        assert classification.details.get("status_code") == 429

    def test_original_error_captured_in_details(self):
        """Verify original_error is captured in classification details."""
        original = ValueError("Original error")
        error = TranscriptionError("Wrapper error", original_error=original)
        classification = classify_error(error)

        assert classification.details.get("original_error_type") == "ValueError"
        assert "Original error" in classification.details.get("original_error_message", "")


class TestRetryableErrorTypes:
    """Verify the error type sets are comprehensive."""

    def test_retryable_error_types_includes_transcription_errors(self):
        """Verify transcription error types are in retryable set."""
        assert "TranscriptionError" in RETRYABLE_ERROR_TYPES
        assert "TranscriptionTimeoutError" in RETRYABLE_ERROR_TYPES
        assert "RateLimitError" in RETRYABLE_ERROR_TYPES
        assert "APIError" in RETRYABLE_ERROR_TYPES
        assert "NetworkError" in RETRYABLE_ERROR_TYPES

    def test_retryable_error_types_includes_notion_errors(self):
        """Verify Notion error types are in retryable set."""
        assert "NotionError" in RETRYABLE_ERROR_TYPES
        assert "NotionRateLimitError" in RETRYABLE_ERROR_TYPES

    def test_retryable_error_types_includes_generic_errors(self):
        """Verify generic retryable error types are in set."""
        assert "TimeoutError" in RETRYABLE_ERROR_TYPES
        assert "ConnectionError" in RETRYABLE_ERROR_TYPES
        assert "OSError" in RETRYABLE_ERROR_TYPES

    def test_non_retryable_error_types_includes_invalid_input(self):
        """Verify invalid input error types are in non-retryable set."""
        assert "InvalidAudioError" in NON_RETRYABLE_ERROR_TYPES
        assert "ValueError" in NON_RETRYABLE_ERROR_TYPES
        assert "TypeError" in NON_RETRYABLE_ERROR_TYPES

    def test_non_retryable_error_types_includes_file_errors(self):
        """Verify file error types are in non-retryable set."""
        assert "FileNotFoundError" in NON_RETRYABLE_ERROR_TYPES

    def test_non_retryable_error_types_includes_auth_errors(self):
        """Verify authentication error types are in non-retryable set."""
        assert "AuthenticationError" in NON_RETRYABLE_ERROR_TYPES
        assert "PermissionError" in NON_RETRYABLE_ERROR_TYPES


# =============================================================================
# Circuit Breaker Tests
# =============================================================================


class TestCircuitBreakerConfig:
    """Tests for circuit breaker configuration."""

    def test_default_config_values(self):
        """Verify default circuit breaker configuration."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60.0
        assert config.half_open_max_requests == 1

    def test_custom_config_values(self):
        """Verify custom configuration values are set."""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=120.0,
            half_open_max_requests=3,
        )
        assert config.failure_threshold == 10
        assert config.recovery_timeout == 120.0
        assert config.half_open_max_requests == 3


class TestCircuitBreaker:
    """Tests for circuit breaker pattern implementation."""

    def test_initial_state_is_closed(self):
        """Verify circuit breaker starts in closed state."""
        breaker = CircuitBreaker()
        assert breaker.state.state == "closed"
        assert breaker.state.failure_count == 0
        assert not breaker.is_open

    def test_should_allow_request_when_closed(self):
        """Verify requests are allowed when circuit is closed."""
        breaker = CircuitBreaker()
        assert breaker.should_allow_request() is True

    def test_circuit_opens_after_threshold_failures(self):
        """Verify circuit opens after failure threshold is reached."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(config=config)

        # Record failures up to threshold
        breaker.record_failure()
        assert not breaker.is_open
        breaker.record_failure()
        assert not breaker.is_open
        breaker.record_failure()
        assert breaker.is_open  # Now open

    def test_should_block_requests_when_open(self):
        """Verify requests are blocked when circuit is open."""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker(config=config)

        breaker.record_failure()  # Opens circuit
        assert breaker.should_allow_request() is False

    def test_success_resets_failure_count(self):
        """Verify success resets the failure count."""
        config = CircuitBreakerConfig(failure_threshold=5)
        breaker = CircuitBreaker(config=config)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state.failure_count == 2

        breaker.record_success()
        assert breaker.state.failure_count == 0
        assert breaker.state.state == "closed"

    def test_circuit_transitions_to_half_open_after_timeout(self):
        """Verify circuit transitions to half-open after recovery timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,  # 100ms for fast test
        )
        breaker = CircuitBreaker(config=config)

        # Open the circuit
        breaker.record_failure()
        assert breaker.is_open

        # Wait for recovery timeout
        time.sleep(0.15)

        # Next request should be allowed (half-open)
        assert breaker.should_allow_request() is True
        assert breaker.is_half_open

    def test_half_open_limits_requests(self):
        """Verify half-open state limits the number of test requests."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.01,
            half_open_max_requests=1,
        )
        breaker = CircuitBreaker(config=config)

        # Open the circuit
        breaker.record_failure()
        time.sleep(0.02)

        # First request allowed (transitions to half-open)
        assert breaker.should_allow_request() is True
        assert breaker.is_half_open  # Confirm we're in half-open state

        # Second request blocked (already used our one allowed request)
        assert breaker.should_allow_request() is False
        # Still half-open, just at the limit
        assert breaker.is_half_open

    def test_success_in_half_open_closes_circuit(self):
        """Verify success in half-open state closes the circuit."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.01,
        )
        breaker = CircuitBreaker(config=config)

        # Open and transition to half-open
        breaker.record_failure()
        time.sleep(0.02)
        breaker.should_allow_request()  # Transition to half-open
        assert breaker.is_half_open

        # Success closes circuit
        breaker.record_success()
        assert breaker.state.state == "closed"
        assert not breaker.is_open

    def test_failure_in_half_open_reopens_circuit(self):
        """Verify failure in half-open state reopens the circuit."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.01,
        )
        breaker = CircuitBreaker(config=config)

        # Open and transition to half-open
        breaker.record_failure()
        time.sleep(0.02)
        breaker.should_allow_request()  # Transition to half-open
        assert breaker.is_half_open

        # Failure reopens circuit
        breaker.record_failure()
        assert breaker.is_open

    def test_reset_returns_to_initial_state(self):
        """Verify reset returns circuit to initial state."""
        breaker = CircuitBreaker()
        breaker.record_failure()
        breaker.record_failure()

        breaker.reset()

        assert breaker.state.state == "closed"
        assert breaker.state.failure_count == 0
        assert breaker.state.last_failure_time is None

    def test_get_status_returns_current_state(self):
        """Verify get_status returns current circuit status."""
        config = CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60.0)
        breaker = CircuitBreaker(config=config)

        breaker.record_failure()
        breaker.record_failure()

        status = breaker.get_status()

        assert status["state"] == "closed"
        assert status["failure_count"] == 2
        assert status["failure_threshold"] == 5
        assert status["recovery_timeout"] == 60.0
        assert status["last_failure_time"] is not None


class TestCircuitOpenError:
    """Tests for CircuitOpenError exception."""

    def test_circuit_open_error_is_retryable(self):
        """Verify CircuitOpenError is marked as retryable."""
        error = CircuitOpenError()
        assert error.retryable is True

    def test_circuit_open_error_message(self):
        """Verify CircuitOpenError has correct default message."""
        error = CircuitOpenError()
        assert str(error) == "Circuit breaker is open"

    def test_circuit_open_error_custom_message(self):
        """Verify CircuitOpenError can have custom message."""
        error = CircuitOpenError("Service temporarily unavailable")
        assert str(error) == "Service temporarily unavailable"


# =============================================================================
# RetryConfig Tests
# =============================================================================


class TestRetryConfigEnhanced:
    """Tests for enhanced RetryConfig functionality."""

    def test_default_values_match_tdd_spec(self):
        """Verify default values match TDD Section 5.2."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_backoff_seconds == 5.0
        assert config.max_backoff_seconds == 300.0
        assert config.backoff_multiplier == 2.0
        assert config.jitter_factor == 0.1

    def test_get_backoff_respects_retry_after(self):
        """Verify get_backoff uses retry_after when provided."""
        config = RetryConfig(jitter_factor=0.0)

        backoff = config.get_backoff(0, retry_after=30.0)
        assert backoff == 30.0

    def test_get_backoff_adds_jitter_to_retry_after(self):
        """Verify jitter is added to retry_after value."""
        config = RetryConfig(jitter_factor=0.1)

        values = [config.get_backoff(0, retry_after=10.0) for _ in range(100)]
        # Should be between 10.0 and 11.0 with 10% jitter
        assert all(10.0 <= v <= 11.0 for v in values)
        # Should have variation
        assert len(set(values)) > 1

    def test_should_retry_error_retryable(self):
        """Verify should_retry_error returns True for retryable errors."""
        config = RetryConfig(max_retries=3)
        error = TranscriptionError("Timeout", retryable=True)

        should_retry, classification = config.should_retry_error(error, 0)

        assert should_retry is True
        assert classification.category == ErrorCategory.RETRYABLE

    def test_should_retry_error_non_retryable(self):
        """Verify should_retry_error returns False for non-retryable errors."""
        config = RetryConfig(max_retries=3)
        error = InvalidAudioError("Invalid format")

        should_retry, classification = config.should_retry_error(error, 0)

        assert should_retry is False
        assert classification.category == ErrorCategory.NON_RETRYABLE

    def test_should_retry_error_at_max_retries(self):
        """Verify should_retry_error returns False at max retries."""
        config = RetryConfig(max_retries=3)
        error = TranscriptionError("Timeout", retryable=True)

        should_retry, classification = config.should_retry_error(error, 3)

        assert should_retry is False
        # Error is still retryable, but we've hit the limit
        assert classification.category == ErrorCategory.RETRYABLE

    def test_circuit_breaker_config_can_be_attached(self):
        """Verify circuit breaker config can be attached to retry config."""
        circuit_config = CircuitBreakerConfig(failure_threshold=10)
        retry_config = RetryConfig(circuit_breaker_config=circuit_config)

        assert retry_config.circuit_breaker_config is not None
        assert retry_config.circuit_breaker_config.failure_threshold == 10


class TestStandardRetryConfigs:
    """Tests for standard retry configurations."""

    def test_pipeline_retry_config_has_circuit_breaker(self):
        """Verify pipeline config includes circuit breaker."""
        assert PIPELINE_RETRY_CONFIG.circuit_breaker_config is not None
        assert PIPELINE_RETRY_CONFIG.circuit_breaker_config.failure_threshold == 5

    def test_transcription_retry_config_values(self):
        """Verify transcription retry config values."""
        assert TRANSCRIPTION_RETRY_CONFIG.max_retries == 3
        assert TRANSCRIPTION_RETRY_CONFIG.base_backoff_seconds == 5.0

    def test_classification_retry_config_values(self):
        """Verify classification retry config values."""
        assert CLASSIFICATION_RETRY_CONFIG.max_retries == 3
        assert CLASSIFICATION_RETRY_CONFIG.base_backoff_seconds == 5.0

    def test_notion_retry_config_values(self):
        """Verify Notion retry config values."""
        assert NOTION_RETRY_CONFIG.max_retries == 3
        assert NOTION_RETRY_CONFIG.base_backoff_seconds == 5.0


# =============================================================================
# Error Logging Tests
# =============================================================================


class TestBuildDetailedErrorLog:
    """Tests for detailed error log building."""

    def test_includes_basic_fields(self):
        """Verify basic fields are included in error log."""
        error = TranscriptionError("Connection timeout", retryable=True)
        classification = classify_error(error)

        log = build_detailed_error_log(
            capture_id=42,
            stage="transcribing",
            error=error,
            retry_count=1,
            classification=classification,
        )

        assert log["capture_id"] == 42
        assert log["stage"] == "transcribing"
        assert log["error_type"] == "TranscriptionError"
        assert "Connection timeout" in log["error_message"]
        assert log["retry_count"] == 1

    def test_includes_error_category(self):
        """Verify error category is included."""
        error = TranscriptionError("Timeout", retryable=True)
        classification = classify_error(error)

        log = build_detailed_error_log(
            capture_id=1,
            stage="transcribing",
            error=error,
            retry_count=0,
            classification=classification,
        )

        assert log["error_category"] == "retryable"
        assert log["is_retryable"] is True

    def test_includes_retry_after_hint(self):
        """Verify retry_after hint is included when present."""
        error = RateLimitError("Rate limited", retry_after=30.0)
        classification = classify_error(error)

        log = build_detailed_error_log(
            capture_id=1,
            stage="transcribing",
            error=error,
            retry_count=0,
            classification=classification,
        )

        assert log.get("retry_after_hint") == 30.0

    def test_includes_traceback(self):
        """Verify traceback is included for debugging."""
        error = TranscriptionError("Error")
        classification = classify_error(error)

        log = build_detailed_error_log(
            capture_id=1,
            stage="transcribing",
            error=error,
            retry_count=0,
            classification=classification,
        )

        assert "traceback" in log

    def test_includes_original_error_details(self):
        """Verify original error details are captured."""
        original = ConnectionError("Network unreachable")
        error = TranscriptionError("Wrapper", original_error=original)
        classification = classify_error(error)

        log = build_detailed_error_log(
            capture_id=1,
            stage="transcribing",
            error=error,
            retry_count=0,
            classification=classification,
        )

        assert log.get("original_error_type") == "ConnectionError"
        assert "Network unreachable" in log.get("original_error_message", "")


# =============================================================================
# Orchestrator Integration Tests
# =============================================================================


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_db():
    """Create a mock database instance."""
    db = MagicMock()

    db.get_capture_by_id = AsyncMock()
    db.get_pending_captures = AsyncMock(return_value=[])
    db.update_status = AsyncMock(return_value=True)
    db.update_transcription = AsyncMock(return_value=True)
    db.update_classification = AsyncMock(return_value=True)
    db.update_notion_result = AsyncMock(return_value=True)
    db.mark_complete = AsyncMock(return_value=True)
    db.log_failure = AsyncMock(return_value=1)
    db.increment_retry = AsyncMock(return_value=1)
    db.update_current_path = AsyncMock(return_value=True)

    return db


@pytest.fixture
def mock_transcription():
    """Create a mock transcription service."""
    service = MagicMock()
    service.transcribe = AsyncMock(
        return_value=TranscriptionResult(
            text="This is a test transcription.",
            duration_seconds=10.5,
            language="english",
        )
    )
    return service


@pytest.fixture
def mock_notion():
    """Create a mock Notion service."""
    service = MagicMock()
    service.create_capture_page = AsyncMock(
        return_value=NotionPage(
            id="test-page-id-123",
            url="https://notion.so/test-page-id-123",
        )
    )
    return service


@pytest.fixture
def sample_capture(temp_dir: Path) -> CaptureRow:
    """Create a sample capture record with a real file."""
    audio_file = temp_dir / "test_audio.m4a"
    audio_file.write_bytes(b"fake audio content")

    return CaptureRow(
        id=1,
        filename="test_audio.m4a",
        original_path=str(audio_file),
        current_path=str(audio_file),
        device="watch",
        captured_at=datetime(2026, 1, 20, 14, 30, 0),
        status="pending",
        retry_count=0,
        transcript=None,
        transcript_duration_seconds=None,
        transcript_language=None,
        template_name=None,
        classification_confidence=None,
        extracted_fields=None,
        suggested_title=None,
        tags=None,
        notion_page_id=None,
        notion_page_url=None,
    )


class TestOrchestratorCircuitBreaker:
    """Tests for circuit breaker integration in orchestrator."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_requests_when_open(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify circuit breaker blocks requests when open."""
        circuit_config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout=60.0)
        retry_config = RetryConfig(circuit_breaker_config=circuit_config)

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=retry_config,
            failed_path=temp_dir / "failed",
        )

        # Open the circuit manually
        orchestrator._circuit_breaker.record_failure()
        assert orchestrator._circuit_breaker.is_open

        # Try to process - should be blocked
        result = await orchestrator.process_capture(1)

        assert result.success is False
        assert result.circuit_open is True
        assert "Circuit breaker" in result.error

    @pytest.mark.asyncio
    async def test_circuit_breaker_status_available(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify circuit breaker status can be retrieved."""
        circuit_config = CircuitBreakerConfig(failure_threshold=5)
        retry_config = RetryConfig(circuit_breaker_config=circuit_config)

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=retry_config,
            failed_path=temp_dir / "failed",
        )

        status = orchestrator.get_circuit_breaker_status()

        assert status is not None
        assert status["state"] == "closed"
        assert status["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_can_be_reset(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify circuit breaker can be manually reset."""
        circuit_config = CircuitBreakerConfig(failure_threshold=1)
        retry_config = RetryConfig(circuit_breaker_config=circuit_config)

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=retry_config,
            failed_path=temp_dir / "failed",
        )

        # Open the circuit
        orchestrator._circuit_breaker.record_failure()
        assert orchestrator._circuit_breaker.is_open

        # Reset
        orchestrator.reset_circuit_breaker()
        assert not orchestrator._circuit_breaker.is_open


class TestOrchestratorStatePreservation:
    """Tests for state preservation on retry."""

    @pytest.mark.asyncio
    async def test_existing_transcript_preserved_on_retry(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify existing transcript is not lost on retry from later stage."""
        # Create capture with existing transcript
        audio_file = temp_dir / "test.m4a"
        audio_file.write_bytes(b"fake audio")

        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(audio_file),
            current_path=str(audio_file),
            status="pending",
            retry_count=0,
            transcript="Existing transcript from previous attempt",
            transcript_duration_seconds=15.0,
            transcript_language="english",
        )

        mock_db.get_capture_by_id = AsyncMock(return_value=capture)

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(base_backoff_seconds=0.01),
            failed_path=temp_dir / "failed",
        )

        # Process - should skip transcription since transcript exists
        await orchestrator.process_capture(1)

        # Transcription should NOT have been called
        mock_transcription.transcribe.assert_not_called()

        # Should have progressed to posting
        status_calls = [call[0][1] for call in mock_db.update_status.call_args_list]
        assert "posting" in status_calls

    @pytest.mark.asyncio
    async def test_existing_classification_preserved_on_retry(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify existing classification is not lost on retry from posting stage."""
        audio_file = temp_dir / "test.m4a"
        audio_file.write_bytes(b"fake audio")

        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(audio_file),
            current_path=str(audio_file),
            status="classifying",
            retry_count=0,
            transcript="Test transcript",
            transcript_duration_seconds=10.0,
            transcript_language="english",
            template_name="task",
            classification_confidence=0.95,
            extracted_fields={"description": "Test task"},
            suggested_title="Test Task",
            tags=["work"],
        )

        async def update_status(cid, status, **kwargs):
            capture.status = status
            return True

        mock_db.get_capture_by_id = AsyncMock(return_value=capture)
        mock_db.update_status = AsyncMock(side_effect=update_status)

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(base_backoff_seconds=0.01),
            failed_path=temp_dir / "failed",
        )

        # Process - should skip classification since it already exists
        await orchestrator.process_capture(1)

        # Should have jumped to posting
        status_calls = [call[0][1] for call in mock_db.update_status.call_args_list]
        assert "posting" in status_calls


class TestOrchestratorErrorHandling:
    """Tests for enhanced error handling in orchestrator."""

    @pytest.mark.asyncio
    async def test_non_retryable_error_fails_immediately(
        self, mock_db, mock_transcription, mock_notion, sample_capture, temp_dir
    ):
        """Verify non-retryable errors fail immediately without retry."""
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail with non-retryable error
        mock_transcription.transcribe = AsyncMock(
            side_effect=InvalidAudioError("Invalid format")
        )

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(max_retries=3),
            failed_path=temp_dir / "failed",
        )

        await orchestrator.process_capture(sample_capture.id)

        # Should NOT have incremented retry
        mock_db.increment_retry.assert_not_called()

        # Should have moved to failed
        failed_calls = [
            call for call in mock_db.update_status.call_args_list
            if call[0][1] == "failed"
        ]
        assert len(failed_calls) == 1

    @pytest.mark.asyncio
    async def test_retryable_error_increments_retry_count(
        self, mock_db, mock_transcription, mock_notion, sample_capture, temp_dir
    ):
        """Verify retryable errors increment retry count."""
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail with retryable error
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(max_retries=3, base_backoff_seconds=0.01),
            failed_path=temp_dir / "failed",
        )

        await orchestrator.process_capture(sample_capture.id)

        # Should have incremented retry
        mock_db.increment_retry.assert_called_once()

        # Should have logged failure with details
        mock_db.log_failure.assert_called_once()
        call_kwargs = mock_db.log_failure.call_args.kwargs
        assert call_kwargs["error_type"] == "TranscriptionError"
        assert "error_details" in call_kwargs

    @pytest.mark.asyncio
    async def test_error_details_logged_to_failure_log(
        self, mock_db, mock_transcription, mock_notion, sample_capture, temp_dir
    ):
        """Verify detailed error information is logged."""
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail with rate limit error that has retry_after
        mock_transcription.transcribe = AsyncMock(
            side_effect=RateLimitError("Rate limited", retry_after=30.0)
        )

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(max_retries=3, base_backoff_seconds=0.01),
            failed_path=temp_dir / "failed",
        )

        await orchestrator.process_capture(sample_capture.id)

        # Check error details in log_failure call
        call_kwargs = mock_db.log_failure.call_args.kwargs
        error_details = call_kwargs["error_details"]

        assert error_details["error_category"] == "retryable"
        assert error_details["is_retryable"] is True
        assert error_details.get("retry_after_hint") == 30.0


class TestOrchestratorProcessingResultCategory:
    """Tests for error category in ProcessingResult."""

    @pytest.mark.asyncio
    async def test_processing_result_includes_error_category(
        self, mock_db, mock_transcription, mock_notion, sample_capture, temp_dir
    ):
        """Verify ProcessingResult includes error category."""
        sample_capture.retry_count = 3  # At max retries

        async def update_status(cid, status, **kwargs):
            sample_capture.status = status
            if kwargs.get("error"):
                sample_capture.last_error = kwargs["error"]
            return True

        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)
        mock_db.update_status = AsyncMock(side_effect=update_status)

        # Fail with retryable error but at max retries
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(max_retries=3, base_backoff_seconds=0.01),
            failed_path=temp_dir / "failed",
        )

        result = await orchestrator.process_capture(sample_capture.id)

        assert result.success is False
        assert result.stage == "transcribing"
        # Error category should be present
        assert result.error_category is not None


class TestRetryFromStage:
    """Tests for retry_failed with stage preservation."""

    @pytest.mark.asyncio
    async def test_retry_from_posting_preserves_state(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify retrying from posting stage preserves transcript and classification."""
        audio_file = temp_dir / "test.m4a"
        audio_file.write_bytes(b"fake audio")

        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(audio_file),
            current_path=str(audio_file),
            status="failed",
            retry_count=1,
            transcript="Preserved transcript",
            transcript_duration_seconds=10.0,
            transcript_language="english",
            template_name="task",
            classification_confidence=0.9,
            extracted_fields={},
            suggested_title="Test",
            tags=[],
            last_error="Previous error",
        )

        async def update_and_return(cid, status, **kwargs):
            capture.status = status
            capture.last_error = kwargs.get("error")
            return True

        mock_db.get_capture_by_id = AsyncMock(return_value=capture)
        mock_db.update_status = AsyncMock(side_effect=update_and_return)

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(base_backoff_seconds=0.01),
            failed_path=temp_dir / "failed",
        )

        await orchestrator.retry_failed(1, from_stage="posting")

        # Should have reset to posting, not pending
        first_update_call = mock_db.update_status.call_args_list[0]
        assert first_update_call[0][1] == "posting"

        # Transcription should NOT have been called (preserved)
        mock_transcription.transcribe.assert_not_called()
