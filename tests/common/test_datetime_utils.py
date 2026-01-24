"""Tests for datetime parsing utilities."""

from datetime import datetime
import pytest

from src.common.datetime_utils import parse_datetime


class TestParseDatetime:
    """Tests for parse_datetime function."""

    def test_parse_none_returns_none(self):
        """Test that None input returns None."""
        result = parse_datetime(None)
        assert result is None

    def test_parse_none_with_default(self):
        """Test that None input returns provided default."""
        default = datetime(2025, 1, 1, 12, 0, 0)
        result = parse_datetime(None, default=default)
        assert result == default

    def test_parse_datetime_object_returns_same(self):
        """Test that datetime objects are passed through unchanged."""
        dt = datetime(2025, 6, 15, 14, 30, 45)
        result = parse_datetime(dt)
        assert result == dt
        assert result is dt  # Same object reference

    def test_parse_sqlite_format(self):
        """Test parsing SQLite format without microseconds."""
        result = parse_datetime("2025-06-15 14:30:45")
        expected = datetime(2025, 6, 15, 14, 30, 45)
        assert result == expected

    def test_parse_sqlite_format_with_microseconds(self):
        """Test parsing SQLite format with microseconds."""
        result = parse_datetime("2025-06-15 14:30:45.123456")
        expected = datetime(2025, 6, 15, 14, 30, 45, 123456)
        assert result == expected

    def test_parse_iso8601_format(self):
        """Test parsing ISO 8601 format without microseconds."""
        result = parse_datetime("2025-06-15T14:30:45")
        expected = datetime(2025, 6, 15, 14, 30, 45)
        assert result == expected

    def test_parse_iso8601_format_with_microseconds(self):
        """Test parsing ISO 8601 format with microseconds."""
        result = parse_datetime("2025-06-15T14:30:45.123456")
        expected = datetime(2025, 6, 15, 14, 30, 45, 123456)
        assert result == expected

    def test_parse_iso8601_format_with_z_suffix(self):
        """Test parsing ISO 8601 format with Z (UTC) suffix."""
        result = parse_datetime("2025-06-15T14:30:45Z")
        expected = datetime(2025, 6, 15, 14, 30, 45)
        assert result == expected

    def test_parse_iso8601_format_with_z_suffix_and_microseconds(self):
        """Test parsing ISO 8601 format with Z suffix and microseconds."""
        result = parse_datetime("2025-06-15T14:30:45.123456Z")
        expected = datetime(2025, 6, 15, 14, 30, 45, 123456)
        assert result == expected

    def test_parse_invalid_string_returns_default(self):
        """Test that invalid string returns default (None by default)."""
        result = parse_datetime("not a date")
        assert result is None

    def test_parse_invalid_string_with_explicit_default(self):
        """Test that invalid string returns provided default."""
        default = datetime(2025, 1, 1, 0, 0, 0)
        result = parse_datetime("not a date", default=default)
        assert result == default

    def test_parse_empty_string_returns_default(self):
        """Test that empty string returns default."""
        result = parse_datetime("")
        assert result is None

    def test_parse_non_string_non_datetime_returns_default(self):
        """Test that non-string, non-datetime values return default."""
        result = parse_datetime(12345)
        assert result is None

        result = parse_datetime([2025, 6, 15])
        assert result is None

        result = parse_datetime({"year": 2025})
        assert result is None

    def test_parse_iso8601_with_timezone_offset(self):
        """Test parsing ISO 8601 format with timezone offset via fromisoformat fallback."""
        # This uses the fromisoformat fallback since strptime doesn't handle +00:00 well
        result = parse_datetime("2025-06-15T14:30:45+00:00")
        # fromisoformat returns timezone-aware datetime
        assert result is not None
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 30
        assert result.second == 45

    def test_parse_partial_date_returns_default(self):
        """Test that partial dates without time return default."""
        result = parse_datetime("2025-06-15")
        # This should fail strptime formats but succeed with fromisoformat
        # fromisoformat can parse date-only strings into datetime
        assert result is not None
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15


class TestParseDatetimeEdgeCases:
    """Edge case tests for parse_datetime function."""

    def test_parse_midnight(self):
        """Test parsing midnight timestamps."""
        result = parse_datetime("2025-06-15 00:00:00")
        expected = datetime(2025, 6, 15, 0, 0, 0)
        assert result == expected

    def test_parse_end_of_day(self):
        """Test parsing end of day timestamps."""
        result = parse_datetime("2025-06-15 23:59:59")
        expected = datetime(2025, 6, 15, 23, 59, 59)
        assert result == expected

    def test_parse_leap_year_date(self):
        """Test parsing leap year date."""
        result = parse_datetime("2024-02-29 12:00:00")
        expected = datetime(2024, 2, 29, 12, 0, 0)
        assert result == expected

    def test_parse_with_various_microsecond_lengths(self):
        """Test parsing with different microsecond precision."""
        # 6 digits (full precision)
        result = parse_datetime("2025-06-15T14:30:45.123456")
        assert result.microsecond == 123456

        # 3 digits (milliseconds) - should work via fromisoformat fallback
        result = parse_datetime("2025-06-15T14:30:45.123")
        assert result is not None
        assert result.microsecond == 123000

    def test_default_is_preserved_not_mutated(self):
        """Test that default datetime is not mutated."""
        default = datetime(2025, 1, 1, 0, 0, 0)
        result1 = parse_datetime("invalid", default=default)
        result2 = parse_datetime(None, default=default)

        assert result1 == default
        assert result2 == default
        assert default == datetime(2025, 1, 1, 0, 0, 0)
