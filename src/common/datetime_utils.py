"""Datetime parsing utilities for Voice Capture.

Provides consistent datetime parsing across the codebase, handling
various formats from SQLite storage and ISO 8601.
"""

from datetime import datetime
from typing import Optional, Union


def parse_datetime(
    value: Union[str, datetime, None],
    default: Optional[datetime] = None
) -> Optional[datetime]:
    """Parse datetime from string or return as-is.

    Handles common formats from SQLite and ISO 8601.

    Args:
        value: String datetime, datetime object, or None
        default: Default value if parsing fails

    Returns:
        Parsed datetime or default value
    """
    if value is None:
        return default
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Handle SQLite format and ISO 8601
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        # Try fromisoformat as fallback for timezone-aware strings
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return default
