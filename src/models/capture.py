"""
Core capture models.

Contains the ProcessingStatus and Device enums, and the CaptureRecord
dataclass representing a voice capture throughout its lifecycle.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import json

from src.common.datetime_utils import parse_datetime as _parse_datetime
from src.models.transcription import TranscriptionResult
from src.models.classification import ClassificationResult


class ProcessingStatus(Enum):
    """
    Processing pipeline states for a capture.

    State machine flow:
    PENDING -> TRANSCRIBING -> CLASSIFYING -> POSTING -> COMPLETE
                    |               |             |
                    v               v             v
                  FAILED         FAILED        FAILED

    Values are lowercase strings for database storage compatibility.
    """
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    CLASSIFYING = "classifying"
    POSTING = "posting"
    COMPLETE = "complete"
    FAILED = "failed"

    @classmethod
    def from_string(cls, value: str) -> "ProcessingStatus":
        """
        Create status from string value.

        Args:
            value: String representation (e.g., "pending", "transcribing").

        Returns:
            Matching ProcessingStatus enum.

        Raises:
            ValueError: If value doesn't match any status.
        """
        value_lower = value.lower()
        for status in cls:
            if status.value == value_lower:
                return status
        raise ValueError(f"Invalid processing status: {value}")

    def can_transition_to(self, next_status: "ProcessingStatus") -> bool:
        """
        Check if transition to next status is valid.

        Valid transitions:
        - PENDING -> TRANSCRIBING
        - TRANSCRIBING -> CLASSIFYING or FAILED
        - CLASSIFYING -> POSTING or FAILED
        - POSTING -> COMPLETE or FAILED
        - FAILED -> PENDING (for retry)

        Args:
            next_status: The target status.

        Returns:
            True if transition is valid.
        """
        valid_transitions = {
            ProcessingStatus.PENDING: {ProcessingStatus.TRANSCRIBING},
            ProcessingStatus.TRANSCRIBING: {ProcessingStatus.CLASSIFYING, ProcessingStatus.FAILED},
            ProcessingStatus.CLASSIFYING: {ProcessingStatus.POSTING, ProcessingStatus.FAILED},
            ProcessingStatus.POSTING: {ProcessingStatus.COMPLETE, ProcessingStatus.FAILED},
            ProcessingStatus.FAILED: {ProcessingStatus.PENDING},  # Allow retry
            ProcessingStatus.COMPLETE: set(),  # Terminal state
        }
        return next_status in valid_transitions.get(self, set())


class Device(Enum):
    """
    Source device for the capture.

    Values are lowercase strings for database storage compatibility.
    """
    WATCH = "watch"
    PHONE = "phone"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "Device":
        """
        Create device from string value.

        Handles iOS Shortcut device type values (e.g., "iPhone" -> phone,
        "Apple Watch" -> watch).

        Args:
            value: String representation (e.g., "watch", "phone", "iPhone").

        Returns:
            Matching Device enum, or UNKNOWN if no match.
        """
        aliases = {
            "iphone": "phone",
            "apple watch": "watch",
            "applewatch": "watch",
        }
        value_lower = value.lower().strip()
        resolved = aliases.get(value_lower, value_lower)
        for device in cls:
            if device.value == resolved:
                return device
        return cls.UNKNOWN


@dataclass
class CaptureRecord:
    """
    Complete record for a voice capture throughout its lifecycle.

    This is the central domain model that tracks a capture from file
    detection through transcription, classification, and Notion posting.

    Attributes:
        id: Database primary key (None for new records).
        filename: Original filename (e.g., "2026-01-20T143022_watch.m4a").
        original_path: Full path where file was first detected.
        current_path: Current file location (changes as file moves through pipeline).
        device: Source device (Watch, Phone, Unknown).
        captured_at: Timestamp extracted from filename or file mtime.

        status: Current processing state.
        retry_count: Number of processing retry attempts.
        last_error: Most recent error message (if any).
        last_attempt_at: Timestamp of last processing attempt.

        transcription: Transcription result (populated after transcription).
        classification: Classification result (populated after classification).

        notion_page_id: Created Notion page ID.
        notion_page_url: URL to the created Notion page.

        created_at: Record creation timestamp.
        updated_at: Last update timestamp.
        completed_at: Successful completion timestamp.
    """
    # Identity
    id: Optional[int] = None
    filename: str = ""
    original_path: str = ""
    current_path: Optional[str] = None
    device: Device = Device.UNKNOWN
    captured_at: Optional[datetime] = None

    # Processing state
    status: ProcessingStatus = ProcessingStatus.PENDING
    retry_count: int = 0
    last_error: Optional[str] = None
    last_attempt_at: Optional[datetime] = None

    # Processing results
    transcription: Optional[TranscriptionResult] = None
    classification: Optional[ClassificationResult] = None

    # Notion results
    notion_page_id: Optional[str] = None
    notion_page_url: Optional[str] = None

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Validate and normalize fields after initialization."""
        # Ensure enums are proper types (handle string conversion)
        if isinstance(self.status, str):
            self.status = ProcessingStatus.from_string(self.status)
        if isinstance(self.device, str):
            self.device = Device.from_string(self.device)

        # Validate retry_count
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for JSON/database serialization.

        Handles special serialization for:
        - Enums -> string values
        - datetime -> ISO format strings
        - Nested dataclasses -> dictionaries

        Returns:
            Dictionary representation suitable for storage.
        """
        result: Dict[str, Any] = {
            "id": self.id,
            "filename": self.filename,
            "original_path": self.original_path,
            "current_path": self.current_path,
            "device": self.device.value,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "transcription": self.transcription.to_dict() if self.transcription else None,
            "classification": self.classification.to_dict() if self.classification else None,
            "notion_page_id": self.notion_page_id,
            "notion_page_url": self.notion_page_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        return result

    def to_json(self) -> str:
        """
        Serialize to JSON string.

        Returns:
            JSON string representation.
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaptureRecord":
        """
        Create instance from dictionary.

        Handles special deserialization for:
        - string -> Enum values
        - ISO format strings -> datetime
        - dictionaries -> nested dataclasses

        Args:
            data: Dictionary with capture record fields.

        Returns:
            New CaptureRecord instance.
        """
        # Parse nested models
        transcription = None
        if data.get("transcription"):
            transcription = TranscriptionResult.from_dict(data["transcription"])

        classification = None
        if data.get("classification"):
            classification = ClassificationResult.from_dict(data["classification"])

        return cls(
            id=data.get("id"),
            filename=data.get("filename", ""),
            original_path=data.get("original_path", ""),
            current_path=data.get("current_path"),
            device=Device.from_string(data.get("device", "unknown")),
            captured_at=_parse_datetime(data.get("captured_at")),
            status=ProcessingStatus.from_string(data.get("status", "pending")),
            retry_count=data.get("retry_count", 0),
            last_error=data.get("last_error"),
            last_attempt_at=_parse_datetime(data.get("last_attempt_at")),
            transcription=transcription,
            classification=classification,
            notion_page_id=data.get("notion_page_id"),
            notion_page_url=data.get("notion_page_url"),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
            completed_at=_parse_datetime(data.get("completed_at")),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "CaptureRecord":
        """
        Deserialize from JSON string.

        Args:
            json_str: JSON string representation.

        Returns:
            New CaptureRecord instance.
        """
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "CaptureRecord":
        """
        Create instance from database row.

        Handles the flattened database schema where transcription and
        classification fields are stored as separate columns and JSON fields.

        Args:
            row: Dictionary mapping column names to values.

        Returns:
            New CaptureRecord instance.
        """
        # Build transcription result if transcript exists
        transcription = None
        if row.get("transcript"):
            transcription = TranscriptionResult(
                text=row["transcript"],
                duration_seconds=row.get("transcript_duration_seconds", 0),
                language=row.get("transcript_language", "unknown"),
                segments=None,  # Segments not stored in DB
            )

        # Build classification result if template exists
        classification = None
        if row.get("template_name"):
            # Parse JSON fields
            extracted_fields = row.get("extracted_fields")
            if isinstance(extracted_fields, str):
                extracted_fields = json.loads(extracted_fields)
            elif extracted_fields is None:
                extracted_fields = {}

            tags = row.get("tags")
            if isinstance(tags, str):
                tags = json.loads(tags)
            elif tags is None:
                tags = []

            classification = ClassificationResult(
                template_name=row["template_name"],
                confidence=row.get("classification_confidence", 0.0),
                fields=extracted_fields,
                title=row.get("suggested_title", ""),
                tags=tags,
                reasoning=None,  # Reasoning not stored in DB
            )

        return cls(
            id=row.get("id"),
            filename=row.get("filename", ""),
            original_path=row.get("original_path", ""),
            current_path=row.get("current_path"),
            device=Device.from_string(row.get("device", "unknown")),
            captured_at=_parse_datetime(row.get("captured_at")),
            status=ProcessingStatus.from_string(row.get("status", "pending")),
            retry_count=row.get("retry_count", 0),
            last_error=row.get("last_error"),
            last_attempt_at=_parse_datetime(row.get("last_attempt_at")),
            transcription=transcription,
            classification=classification,
            notion_page_id=row.get("notion_page_id"),
            notion_page_url=row.get("notion_page_url"),
            created_at=_parse_datetime(row.get("created_at")),
            updated_at=_parse_datetime(row.get("updated_at")),
            completed_at=_parse_datetime(row.get("completed_at")),
        )

    def to_db_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary matching database schema.

        Flattens nested transcription and classification results into
        their respective column formats.

        Returns:
            Dictionary ready for database insertion/update.
        """
        result: Dict[str, Any] = {
            "filename": self.filename,
            "original_path": self.original_path,
            "current_path": self.current_path,
            "device": self.device.value,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "notion_page_id": self.notion_page_id,
            "notion_page_url": self.notion_page_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

        # Include id only if set
        if self.id is not None:
            result["id"] = self.id

        # Flatten transcription
        if self.transcription:
            result["transcript"] = self.transcription.text
            result["transcript_duration_seconds"] = self.transcription.duration_seconds
            result["transcript_language"] = self.transcription.language
        else:
            result["transcript"] = None
            result["transcript_duration_seconds"] = None
            result["transcript_language"] = None

        # Flatten classification
        if self.classification:
            result["template_name"] = self.classification.template_name
            result["classification_confidence"] = self.classification.confidence
            result["extracted_fields"] = json.dumps(self.classification.fields)
            result["suggested_title"] = self.classification.title
            result["tags"] = json.dumps(self.classification.tags)
        else:
            result["template_name"] = None
            result["classification_confidence"] = None
            result["extracted_fields"] = None
            result["suggested_title"] = None
            result["tags"] = None

        return result

    def is_terminal(self) -> bool:
        """
        Check if capture is in a terminal state.

        Returns:
            True if status is COMPLETE or FAILED.
        """
        return self.status in (ProcessingStatus.COMPLETE, ProcessingStatus.FAILED)

    def is_retryable(self, max_retries: int = 3) -> bool:
        """
        Check if capture can be retried.

        Args:
            max_retries: Maximum allowed retry attempts.

        Returns:
            True if status is FAILED and retry_count < max_retries.
        """
        return self.status == ProcessingStatus.FAILED and self.retry_count < max_retries

    def get_duration_seconds(self) -> Optional[float]:
        """
        Get audio duration from transcription result.

        Returns:
            Duration in seconds, or None if not transcribed.
        """
        if self.transcription:
            return self.transcription.duration_seconds
        return None

    def get_template_name(self) -> Optional[str]:
        """
        Get classified template name.

        Returns:
            Template name, or None if not classified.
        """
        if self.classification:
            return self.classification.template_name
        return None

    def get_title(self) -> str:
        """
        Get the best available title for the capture.

        Priority:
        1. Classification suggested_title
        2. First sentence of transcript
        3. Filename

        Returns:
            Title string.
        """
        if self.classification and self.classification.title:
            return self.classification.title
        if self.transcription and self.transcription.text:
            return self.transcription.get_first_sentence()
        return self.filename
