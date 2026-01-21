"""Retry configuration for pipeline operations.

Provides exponential backoff with jitter calculation per TDD Section 5.2.
"""

import random
from dataclasses import dataclass


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
    """

    max_retries: int = 3
    base_backoff_seconds: float = 5.0
    max_backoff_seconds: float = 300.0  # 5 minutes
    backoff_multiplier: float = 2.0
    jitter_factor: float = 0.1  # 10% jitter

    def get_backoff(self, retry_count: int) -> float:
        """Calculate exponential backoff with jitter.

        Formula: min(base * multiplier^retry_count, max) + jitter

        Jitter adds a random value between 0 and (backoff * jitter_factor)
        to prevent thundering herd effects.

        Args:
            retry_count: Current retry attempt (0-based).
                         0 = first retry, 1 = second retry, etc.

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
        # Calculate base exponential backoff
        backoff = min(
            self.base_backoff_seconds * (self.backoff_multiplier ** retry_count),
            self.max_backoff_seconds,
        )

        # Add jitter (random value between 0 and jitter_factor * backoff)
        jitter = backoff * self.jitter_factor * random.random()

        return backoff + jitter

    def should_retry(self, current_retry_count: int) -> bool:
        """Check if another retry attempt is allowed.

        Args:
            current_retry_count: Number of retries already attempted.

        Returns:
            True if more retries are allowed.
        """
        return current_retry_count < self.max_retries
