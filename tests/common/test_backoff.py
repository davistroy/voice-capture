"""Tests for src.common.backoff module.

Tests the exponential backoff with jitter utility that is shared
across multiple modules in the codebase.
"""

import random
from unittest.mock import patch

import pytest

from src.common.backoff import (
    BackoffConfig,
    DEFAULT_CONFIG,
    calculate_backoff,
    calculate_backoff_with_retry_after,
)


class TestBackoffConfig:
    """Tests for BackoffConfig dataclass."""

    def test_default_values(self):
        """Test that default values match expected TDD specifications."""
        config = BackoffConfig()

        assert config.base_seconds == 5.0
        assert config.max_seconds == 300.0
        assert config.multiplier == 2.0
        assert config.jitter_factor == 0.1

    def test_custom_values(self):
        """Test that custom values are properly stored."""
        config = BackoffConfig(
            base_seconds=1.0,
            max_seconds=60.0,
            multiplier=3.0,
            jitter_factor=0.2,
        )

        assert config.base_seconds == 1.0
        assert config.max_seconds == 60.0
        assert config.multiplier == 3.0
        assert config.jitter_factor == 0.2

    def test_default_config_constant(self):
        """Test that DEFAULT_CONFIG has expected values."""
        assert DEFAULT_CONFIG.base_seconds == 5.0
        assert DEFAULT_CONFIG.max_seconds == 300.0
        assert DEFAULT_CONFIG.multiplier == 2.0
        assert DEFAULT_CONFIG.jitter_factor == 0.1


class TestCalculateBackoff:
    """Tests for calculate_backoff function."""

    def test_exponential_growth_with_default_params(self):
        """Test exponential backoff growth pattern with default parameters."""
        # Use fixed random for deterministic testing
        with patch.object(random, 'random', return_value=0.0):
            # With no jitter (random=0), we get exact exponential values
            assert calculate_backoff(0) == 5.0    # 5 * 2^0 = 5
            assert calculate_backoff(1) == 10.0   # 5 * 2^1 = 10
            assert calculate_backoff(2) == 20.0   # 5 * 2^2 = 20
            assert calculate_backoff(3) == 40.0   # 5 * 2^3 = 40
            assert calculate_backoff(4) == 80.0   # 5 * 2^4 = 80
            assert calculate_backoff(5) == 160.0  # 5 * 2^5 = 160
            assert calculate_backoff(6) == 300.0  # capped at max_seconds

    def test_exponential_growth_with_max_jitter(self):
        """Test exponential backoff with maximum jitter."""
        # With full jitter (random=1.0), jitter adds 10% of backoff
        with patch.object(random, 'random', return_value=1.0):
            assert calculate_backoff(0) == 5.5    # 5 + 0.5 (10% of 5)
            assert calculate_backoff(1) == 11.0   # 10 + 1.0 (10% of 10)
            assert calculate_backoff(2) == 22.0   # 20 + 2.0 (10% of 20)

    def test_caps_at_max_seconds(self):
        """Test that backoff is capped at max_seconds."""
        with patch.object(random, 'random', return_value=0.0):
            # At attempt 6: 5 * 2^6 = 320, but capped at 300
            assert calculate_backoff(6) == 300.0
            # At attempt 10: 5 * 2^10 = 5120, but capped at 300
            assert calculate_backoff(10) == 300.0

    def test_jitter_applied_to_capped_value(self):
        """Test that jitter is applied to the capped backoff value."""
        with patch.object(random, 'random', return_value=1.0):
            # At attempt 10: base would be 5120, capped to 300
            # Jitter: 300 * 0.1 * 1.0 = 30
            # Total: 300 + 30 = 330
            assert calculate_backoff(10) == 330.0

    def test_custom_parameters(self):
        """Test with custom base, max, multiplier, and jitter."""
        with patch.object(random, 'random', return_value=0.5):
            result = calculate_backoff(
                attempt=2,
                base_seconds=1.0,
                max_seconds=100.0,
                multiplier=3.0,
                jitter_factor=0.2,
            )
            # base: 1 * 3^2 = 9
            # jitter: 9 * 0.2 * 0.5 = 0.9
            # total: 9 + 0.9 = 9.9
            assert result == 9.9

    def test_with_config_object(self):
        """Test using BackoffConfig object instead of individual params."""
        config = BackoffConfig(
            base_seconds=2.0,
            max_seconds=50.0,
            multiplier=4.0,
            jitter_factor=0.05,
        )

        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff(attempt=2, config=config)
            # base: 2 * 4^2 = 32
            # jitter: 0 (random=0)
            assert result == 32.0

    def test_config_overrides_individual_params(self):
        """Test that config object takes precedence over individual params."""
        config = BackoffConfig(base_seconds=100.0)

        with patch.object(random, 'random', return_value=0.0):
            # Individual params should be ignored when config is provided
            result = calculate_backoff(
                attempt=0,
                config=config,
                base_seconds=1.0,  # Should be ignored
            )
            assert result == 100.0  # Uses config.base_seconds

    def test_attempt_zero(self):
        """Test that attempt=0 uses base value."""
        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff(0)
            assert result == 5.0  # base * 2^0 = 5 * 1 = 5

    def test_jitter_is_positive_only(self):
        """Test that jitter only adds positive values (0 to jitter_factor * backoff)."""
        # Run multiple times with different random values
        results = []
        for _ in range(100):
            result = calculate_backoff(0)
            results.append(result)

        # All results should be between 5.0 and 5.5 (base + max 10% jitter)
        assert all(5.0 <= r <= 5.5 for r in results)

    def test_jitter_distribution(self):
        """Test that jitter values are distributed across the range."""
        random.seed(42)  # For reproducibility

        results = [calculate_backoff(0) for _ in range(1000)]

        # Should have variety in results (not all the same)
        unique_results = set(results)
        assert len(unique_results) > 100

        # All should be in valid range
        assert all(5.0 <= r <= 5.5 for r in results)

        # Should have some results near both ends
        assert any(r < 5.1 for r in results)
        assert any(r > 5.4 for r in results)


class TestCalculateBackoffWithRetryAfter:
    """Tests for calculate_backoff_with_retry_after function."""

    def test_uses_retry_after_when_provided(self):
        """Test that retry_after value is used when provided."""
        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff_with_retry_after(
                attempt=0,
                retry_after=30.0,
            )
            assert result == 30.0

    def test_adds_jitter_to_retry_after(self):
        """Test that jitter is added to retry_after value."""
        with patch.object(random, 'random', return_value=1.0):
            result = calculate_backoff_with_retry_after(
                attempt=0,
                retry_after=30.0,
            )
            # 30 + (30 * 0.1 * 1.0) = 33.0
            assert result == 33.0

    def test_uses_custom_jitter_factor_with_retry_after(self):
        """Test custom jitter factor with retry_after."""
        with patch.object(random, 'random', return_value=1.0):
            result = calculate_backoff_with_retry_after(
                attempt=0,
                retry_after=30.0,
                jitter_factor=0.2,
            )
            # 30 + (30 * 0.2 * 1.0) = 36.0
            assert result == 36.0

    def test_falls_back_to_exponential_when_retry_after_none(self):
        """Test fallback to exponential backoff when retry_after is None."""
        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff_with_retry_after(
                attempt=2,
                retry_after=None,
            )
            # Should use normal exponential: 5 * 2^2 = 20
            assert result == 20.0

    def test_falls_back_when_retry_after_zero(self):
        """Test fallback when retry_after is 0."""
        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff_with_retry_after(
                attempt=1,
                retry_after=0.0,
            )
            # Should use normal exponential: 5 * 2^1 = 10
            assert result == 10.0

    def test_falls_back_when_retry_after_negative(self):
        """Test fallback when retry_after is negative."""
        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff_with_retry_after(
                attempt=1,
                retry_after=-5.0,
            )
            # Should use normal exponential: 5 * 2^1 = 10
            assert result == 10.0

    def test_with_config_object(self):
        """Test using config object with retry_after."""
        config = BackoffConfig(jitter_factor=0.05)

        with patch.object(random, 'random', return_value=1.0):
            result = calculate_backoff_with_retry_after(
                attempt=0,
                retry_after=20.0,
                config=config,
            )
            # 20 + (20 * 0.05 * 1.0) = 21.0
            assert result == 21.0

    def test_config_fallback_uses_config_params(self):
        """Test that config params are used in fallback case."""
        config = BackoffConfig(
            base_seconds=2.0,
            multiplier=3.0,
        )

        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff_with_retry_after(
                attempt=2,
                retry_after=None,
                config=config,
            )
            # 2 * 3^2 = 18
            assert result == 18.0


class TestBackwardCompatibility:
    """Tests to ensure backward compatibility with existing module behavior."""

    def test_matches_pipeline_retry_behavior(self):
        """Test that behavior matches src/pipeline/retry.py RetryConfig.get_backoff()."""
        # Original behavior: min(base * multiplier^retry_count, max) + jitter
        # Where jitter = backoff * jitter_factor * random()

        with patch.object(random, 'random', return_value=0.5):
            result = calculate_backoff(
                attempt=2,
                base_seconds=5.0,
                max_seconds=300.0,
                multiplier=2.0,
                jitter_factor=0.1,
            )
            # 5 * 2^2 = 20
            # jitter = 20 * 0.1 * 0.5 = 1.0
            # total = 21.0
            assert result == 21.0

    def test_matches_notion_client_behavior(self):
        """Test that behavior matches src/notion/client.py _calculate_backoff()."""
        # Original: min(base * 2^attempt, max) + backoff * 0.1 * random()

        with patch.object(random, 'random', return_value=0.5):
            result = calculate_backoff(
                attempt=3,
                base_seconds=5.0,
                max_seconds=300.0,
                multiplier=2.0,
                jitter_factor=0.1,
            )
            # 5 * 2^3 = 40
            # jitter = 40 * 0.1 * 0.5 = 2.0
            # total = 42.0
            assert result == 42.0

    def test_matches_synthesis_query_behavior(self):
        """Test that behavior matches hardcoded values in notion_query.py."""
        # Original had: base=5.0, max=300.0, multiplier=2, jitter=10%

        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff(
                attempt=4,
                base_seconds=5.0,
                max_seconds=300.0,
                multiplier=2.0,
                jitter_factor=0.1,
            )
            # 5 * 2^4 = 80
            assert result == 80.0


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_high_attempt_number(self):
        """Test behavior with very high attempt numbers."""
        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff(100)
            # Should be capped at max_seconds
            assert result == 300.0

    def test_zero_base_seconds(self):
        """Test with zero base seconds."""
        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff(attempt=5, base_seconds=0.0)
            assert result == 0.0

    def test_zero_jitter_factor(self):
        """Test with zero jitter factor."""
        results = [
            calculate_backoff(attempt=2, jitter_factor=0.0)
            for _ in range(10)
        ]
        # All results should be identical (no randomness)
        assert all(r == 20.0 for r in results)

    def test_high_jitter_factor(self):
        """Test with high jitter factor."""
        with patch.object(random, 'random', return_value=1.0):
            result = calculate_backoff(
                attempt=0,
                base_seconds=10.0,
                jitter_factor=1.0,  # 100% jitter
            )
            # 10 + (10 * 1.0 * 1.0) = 20
            assert result == 20.0

    def test_multiplier_less_than_one(self):
        """Test with multiplier less than 1 (decreasing backoff)."""
        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff(
                attempt=2,
                base_seconds=100.0,
                multiplier=0.5,
            )
            # 100 * 0.5^2 = 25
            assert result == 25.0

    def test_max_less_than_base(self):
        """Test when max_seconds is less than base_seconds."""
        with patch.object(random, 'random', return_value=0.0):
            result = calculate_backoff(
                attempt=0,
                base_seconds=10.0,
                max_seconds=5.0,
            )
            # Should cap at max even at attempt 0
            assert result == 5.0


class TestRandomnessBehavior:
    """Tests to verify randomness properties."""

    def test_repeated_calls_produce_different_results(self):
        """Test that repeated calls produce different results."""
        random.seed(None)  # Use current time for randomness

        results = [calculate_backoff(0) for _ in range(100)]
        unique_results = set(results)

        # Should have significant variety (not all the same)
        assert len(unique_results) > 10

    def test_results_within_expected_range(self):
        """Test that all results fall within expected range."""
        results = [calculate_backoff(0) for _ in range(1000)]

        for result in results:
            # Should be between base (5.0) and base + max_jitter (5.5)
            assert 5.0 <= result <= 5.5

    def test_deterministic_with_seed(self):
        """Test that results are deterministic when random is seeded."""
        random.seed(12345)
        result1 = calculate_backoff(0)

        random.seed(12345)
        result2 = calculate_backoff(0)

        assert result1 == result2
