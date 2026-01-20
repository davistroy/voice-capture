"""Database row models for Voice Capture.

These are lightweight dataclasses representing database rows.
They are distinct from the domain models in src/models/ which will be
created in work item 1.3.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class CaptureRow:
    """Represents a row in the captures table."""

    id: Optional[int] = None
    filename: str = ""
    original_path: str = ""
    current_path: Optional[str] = None
    device: Optional[str] = None
    captured_at: Optional[datetime] = None

    # Processing state
    status: str = "pending"
    retry_count: int = 0
    last_error: Optional[str] = None
    last_attempt_at: Optional[datetime] = None

    # Transcription results
    transcript: Optional[str] = None
    transcript_duration_seconds: Optional[float] = None
    transcript_language: Optional[str] = None

    # Classification results
    template_name: Optional[str] = None
    classification_confidence: Optional[float] = None
    extracted_fields: Optional[dict[str, Any]] = None
    suggested_title: Optional[str] = None
    tags: Optional[list[str]] = None

    # Notion results
    notion_page_id: Optional[str] = None
    notion_page_url: Optional[str] = None

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "CaptureRow":
        """Create a CaptureRow from a database row dictionary."""
        import json

        return cls(
            id=row.get("id"),
            filename=row.get("filename", ""),
            original_path=row.get("original_path", ""),
            current_path=row.get("current_path"),
            device=row.get("device"),
            captured_at=_parse_datetime(row.get("captured_at")),
            status=row.get("status", "pending"),
            retry_count=row.get("retry_count", 0),
            last_error=row.get("last_error"),
            last_attempt_at=_parse_datetime(row.get("last_attempt_at")),
            transcript=row.get("transcript"),
            transcript_duration_seconds=row.get("transcript_duration_seconds"),
            transcript_language=row.get("transcript_language"),
            template_name=row.get("template_name"),
            classification_confidence=row.get("classification_confidence"),
            extracted_fields=_parse_json(row.get("extracted_fields")),
            suggested_title=row.get("suggested_title"),
            tags=_parse_json(row.get("tags")),
            notion_page_id=row.get("notion_page_id"),
            notion_page_url=row.get("notion_page_url"),
            created_at=_parse_datetime(row.get("created_at")),
            updated_at=_parse_datetime(row.get("updated_at")),
            completed_at=_parse_datetime(row.get("completed_at")),
        )


@dataclass
class FailureLogRow:
    """Represents a row in the failure_log table."""

    id: Optional[int] = None
    capture_id: int = 0
    stage: str = ""
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    error_details: Optional[dict[str, Any]] = None
    occurred_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "FailureLogRow":
        """Create a FailureLogRow from a database row dictionary."""
        return cls(
            id=row.get("id"),
            capture_id=row.get("capture_id", 0),
            stage=row.get("stage", ""),
            error_type=row.get("error_type"),
            error_message=row.get("error_message"),
            error_details=_parse_json(row.get("error_details")),
            occurred_at=_parse_datetime(row.get("occurred_at")),
        )


@dataclass
class DailyStatsRow:
    """Represents a row in the daily_stats table."""

    date: str = ""  # YYYY-MM-DD format
    captures_received: int = 0
    captures_completed: int = 0
    captures_failed: int = 0
    total_audio_seconds: float = 0.0
    avg_processing_time_seconds: Optional[float] = None
    template_breakdown: Optional[dict[str, int]] = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DailyStatsRow":
        """Create a DailyStatsRow from a database row dictionary."""
        return cls(
            date=row.get("date", ""),
            captures_received=row.get("captures_received", 0),
            captures_completed=row.get("captures_completed", 0),
            captures_failed=row.get("captures_failed", 0),
            total_audio_seconds=row.get("total_audio_seconds", 0.0),
            avg_processing_time_seconds=row.get("avg_processing_time_seconds"),
            template_breakdown=_parse_json(row.get("template_breakdown")),
        )


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse a datetime value from database."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # SQLite stores datetime as ISO format string
        try:
            # Handle both with and without microseconds
            if "." in value:
                return datetime.fromisoformat(value)
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_json(value: Any) -> Optional[Any]:
    """Parse a JSON value from database."""
    import json

    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None
