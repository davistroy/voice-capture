"""Async SQLite database facade for Voice Capture.

This module provides the Database class which acts as a facade over
the repository pattern implementation. It maintains backward compatibility
with existing code while delegating to specialized repositories.

The facade pattern provides:
- A unified interface for all database operations
- Backward compatibility with existing method signatures
- Access to specialized repositories for advanced use cases
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiosqlite

from src.db.connection import ConnectionPool, SCHEMA_SQL, VALID_STATUSES
from src.db.models import CaptureRow, DailyStatsRow, FailureLogRow
from src.db.repositories import (
    CaptureRepository,
    FailureLogRepository,
    StatisticsRepository,
)

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ["Database", "SCHEMA_SQL", "VALID_STATUSES"]


class Database:
    """Async SQLite database facade with backward-compatible interface.

    Provides connection pooling and all required database operations for
    the voice capture processing pipeline. Internally delegates to
    specialized repository classes.

    For new code, consider using the repository classes directly via
    the `captures`, `failures`, and `statistics` attributes.

    Usage:
        db = Database(Path("/path/to/database.db"))
        await db.initialize()

        # Traditional interface (backward compatible)
        capture_id = await db.insert_capture(...)

        # Repository interface (recommended for new code)
        capture_id = await db.captures.insert(...)

        # Close when done
        await db.close()

    Or use as async context manager:
        async with Database(path) as db:
            await db.insert_capture(...)
    """

    def __init__(self, db_path: Path, pool_size: int = 5):
        """Initialize database facade.

        Args:
            db_path: Path to SQLite database file
            pool_size: Maximum number of connections in pool
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool = ConnectionPool(db_path, pool_size)

        # Initialize repositories
        self.captures = CaptureRepository(self._pool)
        self.failures = FailureLogRepository(self._pool)
        self.statistics = StatisticsRepository(self._pool)

    @property
    def _initialized(self) -> bool:
        """Check if database is initialized (for backward compatibility)."""
        return self._pool.initialized

    async def initialize(self) -> None:
        """Initialize database and create schema.

        Creates the database file and all tables/indexes if they don't exist.
        Safe to call multiple times.
        """
        await self._pool.initialize()

    async def close(self) -> None:
        """Close all database connections."""
        await self._pool.close()

    async def __aenter__(self) -> "Database":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    @asynccontextmanager
    async def _get_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Get a connection from the pool.

        Yields a connection and returns it to the pool when done.
        For internal use and testing.
        """
        async with self._pool.acquire() as conn:
            yield conn

    # =========================================================================
    # Capture Operations (delegating to CaptureRepository)
    # =========================================================================

    async def insert_capture(
        self,
        filename: str,
        original_path: str,
        device: Optional[str] = None,
        captured_at: Optional[datetime] = None,
        current_path: Optional[str] = None,
        source: str = "watcher",
    ) -> int:
        """Insert a new capture record.

        Args:
            filename: Unique filename of the audio file
            original_path: Original path where file was found
            device: Device type ('watch', 'phone', or 'unknown')
            captured_at: Timestamp when audio was captured
            current_path: Current path of the file (if moved)
            source: Upload source ('watcher' for folder watcher, 'http' for HTTP upload)

        Returns:
            ID of the inserted capture record

        Raises:
            sqlite3.IntegrityError: If filename already exists
        """
        return await self.captures.insert(
            filename=filename,
            original_path=original_path,
            device=device,
            captured_at=captured_at,
            current_path=current_path,
            source=source,
        )

    async def update_status(
        self,
        capture_id: int,
        status: str,
        error: Optional[str] = None,
    ) -> bool:
        """Update capture status.

        Args:
            capture_id: ID of the capture to update
            status: New status (must be valid state)
            error: Optional error message

        Returns:
            True if update succeeded, False if capture not found

        Raises:
            ValueError: If status is not a valid state
        """
        return await self.captures.update_status(capture_id, status, error)

    async def get_pending_captures(self) -> list[CaptureRow]:
        """Get all captures with pending status.

        Returns:
            List of CaptureRow objects with status='pending'
        """
        return await self.captures.get_pending()

    async def get_capture_by_id(self, capture_id: int) -> Optional[CaptureRow]:
        """Get a capture by ID.

        Args:
            capture_id: ID of the capture to retrieve

        Returns:
            CaptureRow if found, None otherwise
        """
        return await self.captures.get_by_id(capture_id)

    async def get_capture_by_filename(self, filename: str) -> Optional[CaptureRow]:
        """Get a capture by filename.

        Args:
            filename: Filename to search for

        Returns:
            CaptureRow if found, None otherwise
        """
        return await self.captures.get_by_filename(filename)

    async def increment_retry(self, capture_id: int) -> int:
        """Increment retry count for a capture.

        Args:
            capture_id: ID of the capture

        Returns:
            New retry count

        Raises:
            ValueError: If capture not found
        """
        return await self.captures.increment_retry(capture_id)

    async def update_transcription(
        self,
        capture_id: int,
        transcript: str,
        duration: float,
        language: str,
    ) -> bool:
        """Update transcription results for a capture.

        Args:
            capture_id: ID of the capture
            transcript: Transcribed text
            duration: Audio duration in seconds
            language: Detected language code

        Returns:
            True if update succeeded, False if capture not found
        """
        return await self.captures.update_transcription(
            capture_id, transcript, duration, language
        )

    async def update_classification(
        self,
        capture_id: int,
        template: str,
        confidence: float,
        fields: dict[str, Any],
        title: str,
        tags: list[str],
    ) -> bool:
        """Update classification results for a capture.

        Args:
            capture_id: ID of the capture
            template: Selected template name
            confidence: Classification confidence (0.0-1.0)
            fields: Extracted fields as dictionary
            title: Suggested title
            tags: List of tags

        Returns:
            True if update succeeded, False if capture not found
        """
        return await self.captures.update_classification(
            capture_id, template, confidence, fields, title, tags
        )

    async def update_notion_result(
        self,
        capture_id: int,
        page_id: str,
        page_url: str,
    ) -> bool:
        """Update Notion page information for a capture.

        Args:
            capture_id: ID of the capture
            page_id: Notion page ID
            page_url: Notion page URL

        Returns:
            True if update succeeded, False if capture not found
        """
        return await self.captures.update_notion_result(capture_id, page_id, page_url)

    async def mark_complete(self, capture_id: int) -> bool:
        """Mark a capture as complete.

        Sets status to 'complete' and records completion timestamp.

        Args:
            capture_id: ID of the capture

        Returns:
            True if update succeeded, False if capture not found
        """
        return await self.captures.mark_complete(capture_id)

    async def update_current_path(self, capture_id: int, current_path: str) -> bool:
        """Update the current path of a capture file.

        Args:
            capture_id: ID of the capture
            current_path: New file path

        Returns:
            True if update succeeded, False if capture not found
        """
        return await self.captures.update_current_path(capture_id, current_path)

    async def get_captures_by_status(self, status: str) -> list[CaptureRow]:
        """Get all captures with a specific status.

        Args:
            status: Status to filter by

        Returns:
            List of CaptureRow objects
        """
        return await self.captures.get_by_status(status)

    async def get_captures_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CaptureRow]:
        """Get captures within a date range.

        Args:
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)

        Returns:
            List of CaptureRow objects
        """
        return await self.captures.get_by_date_range(start_date, end_date)

    async def get_captures_by_source(
        self,
        source: str,
        status: Optional[str] = None,
    ) -> list[CaptureRow]:
        """Get captures by upload source.

        Args:
            source: Upload source ('watcher' or 'http')
            status: Optional status filter

        Returns:
            List of CaptureRow objects
        """
        return await self.captures.get_by_source(source, status)

    async def get_source_stats(
        self,
        hours: int = 24,
    ) -> dict[str, dict[str, int]]:
        """Get capture statistics grouped by source.

        Args:
            hours: Number of hours to look back (default 24)

        Returns:
            Dict mapping source to status counts
        """
        return await self.captures.get_source_stats(hours)

    async def get_recent_http_uploads(
        self,
        limit: int = 10,
    ) -> list[CaptureRow]:
        """Get recent HTTP uploads.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of CaptureRow objects, most recent first
        """
        return await self.captures.get_recent_http_uploads(limit)

    async def reset_capture(self, capture_id: int) -> bool:
        """Reset a capture to pending status for reprocessing.

        Clears error state and resets retry count.

        Args:
            capture_id: ID of the capture to reset

        Returns:
            True if reset succeeded, False if capture not found
        """
        return await self.captures.reset(capture_id)

    async def get_queue_depth(self) -> dict[str, int]:
        """Get count of captures by status.

        Returns:
            Dictionary mapping status to count
        """
        return await self.captures.get_queue_depth()

    async def delete_capture(self, capture_id: int) -> bool:
        """Delete a capture and its failure logs.

        Args:
            capture_id: ID of the capture to delete

        Returns:
            True if deletion succeeded, False if capture not found
        """
        return await self.captures.delete(capture_id)

    # =========================================================================
    # Failure Log Operations (delegating to FailureLogRepository)
    # =========================================================================

    async def log_failure(
        self,
        capture_id: int,
        stage: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        error_details: Optional[dict[str, Any]] = None,
    ) -> int:
        """Log a processing failure.

        Args:
            capture_id: ID of the capture that failed
            stage: Processing stage where failure occurred
            error_type: Type/class of error
            error_message: Error message
            error_details: Additional error details as dictionary

        Returns:
            ID of the failure log entry
        """
        return await self.failures.log(
            capture_id, stage, error_type, error_message, error_details
        )

    async def get_failures_for_capture(self, capture_id: int) -> list[FailureLogRow]:
        """Get all failure log entries for a capture.

        Args:
            capture_id: ID of the capture

        Returns:
            List of FailureLogRow objects, ordered by occurrence time
        """
        return await self.failures.get_for_capture(capture_id)

    # =========================================================================
    # Daily Stats Operations (delegating to StatisticsRepository)
    # =========================================================================

    async def get_daily_stats(self, date: str) -> Optional[DailyStatsRow]:
        """Get statistics for a specific date.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            DailyStatsRow if found, None otherwise
        """
        return await self.statistics.get(date)

    async def update_daily_stats(
        self,
        date: str,
        captures_received: Optional[int] = None,
        captures_completed: Optional[int] = None,
        captures_failed: Optional[int] = None,
        total_audio_seconds: Optional[float] = None,
        avg_processing_time_seconds: Optional[float] = None,
        template_breakdown: Optional[dict[str, int]] = None,
    ) -> bool:
        """Update or insert daily statistics.

        Uses INSERT OR REPLACE (upsert) to handle both new and existing records.

        Args:
            date: Date in YYYY-MM-DD format
            captures_received: Number of captures received
            captures_completed: Number of captures completed
            captures_failed: Number of captures failed
            total_audio_seconds: Total audio duration processed
            avg_processing_time_seconds: Average processing time
            template_breakdown: Dictionary of template counts

        Returns:
            True if operation succeeded
        """
        return await self.statistics.update(
            date,
            captures_received,
            captures_completed,
            captures_failed,
            total_audio_seconds,
            avg_processing_time_seconds,
            template_breakdown,
        )

    async def increment_daily_stat(
        self,
        date: str,
        field: str,
        amount: int = 1,
    ) -> int:
        """Increment a daily stat field atomically.

        Args:
            date: Date in YYYY-MM-DD format
            field: Field to increment (captures_received, captures_completed, captures_failed)
            amount: Amount to increment by

        Returns:
            New value of the field
        """
        return await self.statistics.increment(date, field, amount)

    async def get_stats_for_date_range(
        self,
        start_date: str,
        end_date: str,
    ) -> list[DailyStatsRow]:
        """Get daily stats for a date range.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            List of DailyStatsRow objects
        """
        return await self.statistics.get_for_date_range(start_date, end_date)
