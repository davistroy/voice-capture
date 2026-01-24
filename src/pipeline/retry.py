"""Retry configuration and error categorization for pipeline operations.

Provides exponential backoff with jitter calculation per TDD Section 5.2,
plus error categorization (retryable vs non-retryable) and circuit breaker
pattern for sustained failures per work item 3.3.

Work item 6.9: Includes secret masking for error logs.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set, Type

from src.common.backoff import calculate_backoff_with_retry_after
from src.common.secrets import mask_secrets


class ErrorCategory(Enum):
    """Categories of errors for retry decisions.

    Per TDD Section 5.2 and work item 3.3:
    - RETRYABLE: timeout, rate limit, server error, network error
    - NON_RETRYABLE: invalid input, authentication failure
    """
    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"


@dataclass
class ErrorClassification:
    """Classification of an error for retry logic.

    Attributes:
        category: Whether the error is retryable or not.
        error_type: String name of the error type.
        message: Human-readable error message.
        retry_after: Optional hint for how long to wait (e.g., from Retry-After header).
        details: Additional context for logging to failure_log.
    """
    category: ErrorCategory
    error_type: str
    message: str
    retry_after: Optional[float] = None
    details: Optional[dict] = None


# Map of error type names to their default retry behavior
RETRYABLE_ERROR_TYPES: Set[str] = {
    # Transcription errors
    "TranscriptionError",
    "TranscriptionTimeoutError",
    "RateLimitError",
    "APIError",
    "NetworkError",
    # Notion errors
    "NotionError",
    "NotionRateLimitError",
    # Classification errors
    "ClassificationError",
    # Generic errors that are typically retryable
    "TimeoutError",
    "ConnectionError",
    "OSError",
    "IOError",
}

NON_RETRYABLE_ERROR_TYPES: Set[str] = {
    # Transcription errors
    "InvalidAudioError",
    # Authentication/authorization
    "AuthenticationError",
    "PermissionError",
    # Invalid input
    "ValueError",
    "TypeError",
    "KeyError",
    # File issues that won't resolve with retry
    "FileNotFoundError",
}


def classify_error(error: Exception) -> ErrorClassification:
    """Classify an error to determine retry behavior.

    Uses the error type and any retryable attribute to determine if
    the error should trigger a retry.

    Args:
        error: The exception to classify.

    Returns:
        ErrorClassification with category and details for logging.
    """
    error_type = type(error).__name__
    message = str(error)
    retry_after = None
    details = {}

    # Check for explicit retryable attribute (some errors self-declare)
    if hasattr(error, "retryable"):
        if error.retryable:
            category = ErrorCategory.RETRYABLE
        else:
            category = ErrorCategory.NON_RETRYABLE

        # Extract retry_after if present (e.g., rate limit errors)
        if hasattr(error, "retry_after") and error.retry_after:
            retry_after = error.retry_after
            details["retry_after_hint"] = retry_after

    # Check against known error types
    elif error_type in NON_RETRYABLE_ERROR_TYPES:
        category = ErrorCategory.NON_RETRYABLE
    elif error_type in RETRYABLE_ERROR_TYPES:
        category = ErrorCategory.RETRYABLE
    else:
        # Default: unknown errors are retryable (fail-safe)
        category = ErrorCategory.RETRYABLE
        details["unknown_error_type"] = True

    # Add original error info if available
    if hasattr(error, "original_error") and error.original_error:
        details["original_error_type"] = type(error.original_error).__name__
        details["original_error_message"] = str(error.original_error)

    # Add status code if available (HTTP errors)
    if hasattr(error, "status_code") and error.status_code:
        details["status_code"] = error.status_code
        # 4xx errors (except 429) are typically non-retryable
        if 400 <= error.status_code < 500 and error.status_code != 429:
            category = ErrorCategory.NON_RETRYABLE

    return ErrorClassification(
        category=category,
        error_type=error_type,
        message=message,
        retry_after=retry_after,
        details=details if details else None,
    )


@dataclass
class CircuitBreakerState:
    """State tracking for circuit breaker pattern.

    Circuit breaker prevents repeated calls to a failing service.
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service failing, requests blocked immediately
    - HALF_OPEN: Testing if service recovered

    Attributes:
        failure_count: Consecutive failures since last success.
        last_failure_time: Timestamp of most recent failure.
        state: Current circuit state.
        half_open_requests: Requests allowed in half-open state.
    """
    failure_count: int = 0
    last_failure_time: Optional[float] = None
    state: str = "closed"  # closed, open, half_open
    half_open_requests: int = 0


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior.

    Attributes:
        failure_threshold: Number of failures before opening circuit.
        recovery_timeout: Seconds to wait before trying half-open.
        half_open_max_requests: Max requests to try in half-open state.
    """
    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # 1 minute
    half_open_max_requests: int = 1


class CircuitBreaker:
    """Circuit breaker for protecting against sustained failures.

    Implements the circuit breaker pattern to prevent repeated calls
    to a failing service. When failures exceed threshold, the circuit
    opens and immediately rejects requests for a recovery period.

    Usage:
        breaker = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=5))

        if breaker.should_allow_request():
            try:
                result = await make_api_call()
                breaker.record_success()
            except Exception as e:
                breaker.record_failure()
                raise
        else:
            raise CircuitOpenError("Circuit is open, request rejected")
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        """Initialize circuit breaker.

        Args:
            config: Circuit breaker configuration. Uses defaults if None.
        """
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState()

    def should_allow_request(self) -> bool:
        """Check if a request should be allowed.

        Returns:
            True if request can proceed, False if circuit is open.
        """
        current_time = time.time()

        if self.state.state == "closed":
            return True

        elif self.state.state == "open":
            # Check if recovery timeout has passed
            if self.state.last_failure_time:
                elapsed = current_time - self.state.last_failure_time
                if elapsed >= self.config.recovery_timeout:
                    # Transition to half-open
                    self.state.state = "half_open"
                    self.state.half_open_requests = 1  # This request counts
                    return True
            return False

        else:  # half_open
            # Allow limited requests in half-open state
            if self.state.half_open_requests < self.config.half_open_max_requests:
                self.state.half_open_requests += 1
                return True
            return False

    def record_success(self) -> None:
        """Record a successful request.

        Resets failure count and closes circuit if in half-open state.
        """
        self.state.failure_count = 0
        self.state.state = "closed"
        self.state.half_open_requests = 0

    def record_failure(self) -> None:
        """Record a failed request.

        Increments failure count and potentially opens circuit.
        """
        current_time = time.time()
        self.state.failure_count += 1
        self.state.last_failure_time = current_time

        if self.state.state == "half_open":
            # Failed during recovery test, reopen circuit
            self.state.state = "open"
            self.state.half_open_requests = 0

        elif self.state.state == "closed":
            # Check if we've exceeded threshold
            if self.state.failure_count >= self.config.failure_threshold:
                self.state.state = "open"

    def reset(self) -> None:
        """Reset circuit breaker to initial state.

        Useful for manual recovery or testing.
        """
        self.state = CircuitBreakerState()

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self.state.state == "open"

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is in half-open (testing) state."""
        return self.state.state == "half_open"

    def get_status(self) -> dict:
        """Get current circuit breaker status for monitoring.

        Returns:
            Dict with state, failure_count, and time info.
        """
        return {
            "state": self.state.state,
            "failure_count": self.state.failure_count,
            "last_failure_time": self.state.last_failure_time,
            "failure_threshold": self.config.failure_threshold,
            "recovery_timeout": self.config.recovery_timeout,
        }


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and blocking requests."""

    def __init__(self, message: str = "Circuit breaker is open"):
        super().__init__(message)
        self.retryable = True  # Can retry after circuit recovery


@dataclass
class RetryConfig:
    """Configuration for retry behavior with exponential backoff.

    Per TDD Section 5.2:
    - max_retries: 3 (default)
    - base_backoff_seconds: 5.0 (default)
    - max_backoff_seconds: 300.0 (5 minutes, default)
    - backoff_multiplier: 2.0 (default)
    - jitter_factor: 0.1 (10% jitter, default)

    Attributes:
        max_retries: Maximum number of retry attempts before giving up.
        base_backoff_seconds: Initial delay between retries.
        max_backoff_seconds: Maximum delay (cap for exponential growth).
        backoff_multiplier: Multiplier for exponential backoff.
        jitter_factor: Random jitter as fraction of backoff (0.0-1.0).
        circuit_breaker_config: Optional circuit breaker configuration.
    """

    max_retries: int = 3
    base_backoff_seconds: float = 5.0
    max_backoff_seconds: float = 300.0  # 5 minutes
    backoff_multiplier: float = 2.0
    jitter_factor: float = 0.1  # 10% jitter
    circuit_breaker_config: Optional[CircuitBreakerConfig] = None

    def get_backoff(self, retry_count: int, retry_after: Optional[float] = None) -> float:
        """Calculate exponential backoff with jitter.

        If retry_after is provided (e.g., from rate limit response),
        uses that value instead of calculated backoff.

        Formula: min(base * multiplier^retry_count, max) + jitter

        Jitter adds a random value between 0 and (backoff * jitter_factor)
        to prevent thundering herd effects.

        Delegates to src.common.backoff.calculate_backoff_with_retry_after.

        Args:
            retry_count: Current retry attempt (0-based).
                         0 = first retry, 1 = second retry, etc.
            retry_after: Optional explicit wait time (e.g., from Retry-After header).

        Returns:
            Seconds to wait before the next retry attempt.

        Example:
            With default config (base=5, multiplier=2, max=300):
            - retry 0: 5.0-5.5 seconds
            - retry 1: 10.0-11.0 seconds
            - retry 2: 20.0-22.0 seconds
            - retry 3: 40.0-44.0 seconds
            ...capped at 300 + jitter
        """
        return calculate_backoff_with_retry_after(
            attempt=retry_count,
            retry_after=retry_after,
            base_seconds=self.base_backoff_seconds,
            max_seconds=self.max_backoff_seconds,
            multiplier=self.backoff_multiplier,
            jitter_factor=self.jitter_factor,
        )

    def should_retry(self, current_retry_count: int) -> bool:
        """Check if another retry attempt is allowed.

        Args:
            current_retry_count: Number of retries already attempted.

        Returns:
            True if more retries are allowed.
        """
        return current_retry_count < self.max_retries

    def should_retry_error(self, error: Exception, current_retry_count: int) -> tuple[bool, ErrorClassification]:
        """Check if an error should trigger a retry.

        Combines retry count check with error classification.

        Args:
            error: The exception that was raised.
            current_retry_count: Number of retries already attempted.

        Returns:
            Tuple of (should_retry: bool, classification: ErrorClassification).
        """
        classification = classify_error(error)

        # Non-retryable errors fail immediately
        if classification.category == ErrorCategory.NON_RETRYABLE:
            return False, classification

        # Check retry count
        if not self.should_retry(current_retry_count):
            return False, classification

        return True, classification


def build_detailed_error_log(
    capture_id: int,
    stage: str,
    error: Exception,
    retry_count: int,
    classification: ErrorClassification,
) -> dict:
    """Build a detailed error log entry for the failure_log table.

    Per work item 3.3: Improve error messages in failure_log table.
    Per work item 6.9: Masks any secrets that may appear in error messages.

    Args:
        capture_id: ID of the capture being processed.
        stage: Processing stage where error occurred.
        error: The exception that was raised.
        retry_count: Current retry count.
        classification: Error classification result.

    Returns:
        Dict with comprehensive error details for logging (secrets masked).
    """
    details = {
        "capture_id": capture_id,
        "stage": stage,
        "error_type": classification.error_type,
        "error_message": mask_secrets(classification.message),
        "error_category": classification.category.value,
        "retry_count": retry_count,
        "is_retryable": classification.category == ErrorCategory.RETRYABLE,
    }

    # Add retry_after hint if present
    if classification.retry_after:
        details["retry_after_hint"] = classification.retry_after

    # Add classification details (mask any error messages in details)
    if classification.details:
        masked_details = {}
        for key, value in classification.details.items():
            if isinstance(value, str) and "error" in key.lower():
                masked_details[key] = mask_secrets(value)
            else:
                masked_details[key] = value
        details.update(masked_details)

    # Add traceback info for debugging (masked for secrets)
    import traceback
    details["traceback"] = mask_secrets(traceback.format_exc())

    return details


# Standard retry configurations for different services
TRANSCRIPTION_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_backoff_seconds=5.0,
    max_backoff_seconds=300.0,
    backoff_multiplier=2.0,
    jitter_factor=0.1,
)

CLASSIFICATION_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_backoff_seconds=5.0,
    max_backoff_seconds=300.0,
    backoff_multiplier=2.0,
    jitter_factor=0.1,
)

NOTION_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_backoff_seconds=5.0,
    max_backoff_seconds=300.0,
    backoff_multiplier=2.0,
    jitter_factor=0.1,
)

# Pipeline retry config (coordinates all services)
PIPELINE_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_backoff_seconds=5.0,
    max_backoff_seconds=300.0,
    backoff_multiplier=2.0,
    jitter_factor=0.1,
    circuit_breaker_config=CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=60.0,
        half_open_max_requests=1,
    ),
)
