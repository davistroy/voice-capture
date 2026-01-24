"""Exponential backoff with jitter utility.

Provides a unified implementation of exponential backoff with jitter
for retry logic across all modules. This eliminates code duplication
and ensures consistent behavior.

Work item 6.1: Extract Shared Backoff Utility.
"""

import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class BackoffConfig:
    """Configuration for exponential backoff calculation.

    Attributes:
        base_seconds: Base wait time in seconds (default 5.0).
        max_seconds: Maximum wait time in seconds (default 300.0 = 5 minutes).
        multiplier: Exponential multiplier (default 2.0).
        jitter_factor: Random jitter as fraction of backoff, 0.0-1.0 (default 0.1 = 10%).
    """

    base_seconds: float = 5.0
    max_seconds: float = 300.0
    multiplier: float = 2.0
    jitter_factor: float = 0.1


# Default configuration matching existing behavior across the codebase
DEFAULT_CONFIG = BackoffConfig()


def calculate_backoff(
    attempt: int,
    config: Optional[BackoffConfig] = None,
    *,
    base_seconds: float = 5.0,
    max_seconds: float = 300.0,
    multiplier: float = 2.0,
    jitter_factor: float = 0.1,
) -> float:
    """Calculate exponential backoff with jitter.

    Computes a delay time using exponential backoff with optional jitter
    to prevent thundering herd effects when multiple clients retry
    simultaneously.

    Formula: min(base * multiplier^attempt, max) + jitter
    Where jitter is a random value between 0 and (backoff * jitter_factor).

    Args:
        attempt: Attempt number (0-indexed). First retry = 0, second = 1, etc.
        config: Optional BackoffConfig object. If provided, overrides individual
                parameters.
        base_seconds: Base wait time in seconds (default 5.0).
        max_seconds: Maximum wait time in seconds (default 300.0).
        multiplier: Exponential multiplier (default 2.0).
        jitter_factor: Random jitter factor, 0.0-1.0 (default 0.1 = 10%).

    Returns:
        Calculated backoff time in seconds (always >= 0).

    Examples:
        With default config (base=5, multiplier=2, max=300, jitter=0.1):
        - attempt 0: 5.0-5.5 seconds
        - attempt 1: 10.0-11.0 seconds
        - attempt 2: 20.0-22.0 seconds
        - attempt 3: 40.0-44.0 seconds
        - ...capped at 300 + jitter (300-330 seconds)

        Using a config object:
        >>> cfg = BackoffConfig(base_seconds=1.0, multiplier=3.0)
        >>> delay = calculate_backoff(2, config=cfg)

        Using keyword arguments:
        >>> delay = calculate_backoff(2, base_seconds=1.0, multiplier=3.0)
    """
    # Use config if provided, otherwise use individual parameters
    if config is not None:
        base_seconds = config.base_seconds
        max_seconds = config.max_seconds
        multiplier = config.multiplier
        jitter_factor = config.jitter_factor

    # Calculate base exponential backoff
    backoff = min(
        base_seconds * (multiplier ** attempt),
        max_seconds,
    )

    # Add jitter (random value between 0 and jitter_factor * backoff)
    jitter = backoff * jitter_factor * random.random()

    return backoff + jitter


def calculate_backoff_with_retry_after(
    attempt: int,
    retry_after: Optional[float] = None,
    config: Optional[BackoffConfig] = None,
    *,
    base_seconds: float = 5.0,
    max_seconds: float = 300.0,
    multiplier: float = 2.0,
    jitter_factor: float = 0.1,
) -> float:
    """Calculate backoff with optional Retry-After hint.

    If a retry_after value is provided (e.g., from an HTTP Retry-After header),
    uses that value as the base delay. Otherwise, calculates exponential backoff.

    In both cases, a small jitter is added to prevent thundering herd effects.

    Args:
        attempt: Attempt number (0-indexed).
        retry_after: Optional explicit wait time hint (e.g., from Retry-After header).
        config: Optional BackoffConfig object.
        base_seconds: Base wait time in seconds (default 5.0).
        max_seconds: Maximum wait time in seconds (default 300.0).
        multiplier: Exponential multiplier (default 2.0).
        jitter_factor: Random jitter factor, 0.0-1.0 (default 0.1 = 10%).

    Returns:
        Calculated backoff time in seconds.

    Example:
        >>> # Rate limited response with Retry-After: 30
        >>> delay = calculate_backoff_with_retry_after(2, retry_after=30.0)
        >>> # Returns approximately 30-33 seconds (30 + 10% jitter)
    """
    # Get jitter_factor from config if provided
    if config is not None:
        jitter_factor = config.jitter_factor

    # Use explicit retry_after if provided and positive
    if retry_after is not None and retry_after > 0:
        jitter = retry_after * jitter_factor * random.random()
        return retry_after + jitter

    # Fall back to standard exponential backoff
    return calculate_backoff(
        attempt=attempt,
        config=config,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
        multiplier=multiplier,
        jitter_factor=jitter_factor,
    )
