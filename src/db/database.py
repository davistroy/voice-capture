"""Async SQLite database operations for Voice Capture.

Uses aiosqlite for async connection management with a simple connection pool.
All JSON fields are stored as TEXT with json.dumps/loads.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiosqlite

from src.db.models import CaptureRow, DailyStatsRow, FailureLogRow

logger = logging.getLogger(__name__)


# Schema definition matching TDD Section 3.1 exactly
SCHEMA_SQL = """
-- Main processing queue
CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    original_path TEXT NOT NULL,
    current_path TEXT,
    device TEXT,
    captured_at TIMESTAMP,
    source TEXT DEFAULT 'watcher',  -- Upload source: 'watcher' or 'http'

    -- Processing state
    status TEXT NOT NULL DEFAULT 'pending',
    -- Values: pending, transcribing, classifying, posting, complete, failed

    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    last_attempt_at TIMESTAMP,

    -- Transcription results
    transcript TEXT,
    transcript_duration_seconds REAL,
    transcript_language TEXT,

    -- Classification results
    template_name TEXT,
    classification_confidence REAL,
    extracted_fields JSON,
    suggested_title TEXT,
    tags JSON,

    -- Notion results
    notion_page_id TEXT,
    notion_page_url TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_captures_status ON captures(status);
CREATE INDEX IF NOT EXISTS idx_captures_captured_at ON captures(captured_at);
CREATE INDEX IF NOT EXISTS idx_captures_source ON captures(source);

-- Failure history for debugging
CREATE TABLE IF NOT EXISTS failure_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    error_details JSON,
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (capture_id) REFERENCES captures(id)
);

CREATE INDEX IF NOT EXISTS idx_failure_log_capture_id ON failure_log(capture_id);

-- Daily statistics for health monitoring
CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    captures_received INTEGER DEFAULT 0,
    captures_completed INTEGER DEFAULT 0,
    captures_failed INTEGER DEFAULT 0,
    total_audio_seconds REAL DEFAULT 0,
    avg_processing_time_seconds REAL,
    template_breakdown JSON
);
"""

# Valid status values for state machine
VALID_STATUSES = {"pending", "transcribing", "classifying", "posting", "complete", "failed"}


class Database:
    """Async SQLite database connection manager with CRUD operations.

    Provides connection pooling and all required database operations for
    the voice capture processing pipeline.

    Usage:
        db = Database(Path("/path/to/database.db"))
        await db.initialize()

        # Use database
        capture_id = await db.insert_capture(...)

        # Close when done
        await db.close()

    Or use as async context manager:
        async with Database(path) as db:
            await db.insert_capture(...)
    """

    def __init__(self, db_path: Path, pool_size: int = 5):
        """Initialize database manager.

        Args:
            db_path: Path to SQLite database file
            pool_size: Maximum number of connections in pool
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(maxsize=pool_size)
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize database and create schema.

        Creates the database file and all tables/indexes if they don't exist.
        Safe to call multiple times.
        """
        async with self._lock:
            if self._initialized:
                return

            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Create initial connection to setup schema
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            try:
                await conn.executescript(SCHEMA_SQL)
                await conn.commit()
                logger.info(f"Database initialized at {self.db_path}")
            finally:
                await conn.close()

            # Pre-populate connection pool
            for _ in range(self.pool_size):
                conn = await aiosqlite.connect(self.db_path)
                conn.row_factory = aiosqlite.Row
                await self._pool.put(conn)

            self._initialized = True

    async def close(self) -> None:
        """Close all database connections."""
        async with self._lock:
            if not self._initialized:
                return

            while not self._pool.empty():
                conn = await self._pool.get()
                await conn.close()

            self._initialized = False
            logger.info("Database connections closed")

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
        """
        if not self._initialized:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    # =========================================================================
    # Capture CRUD Operations
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
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO captures (filename, original_path, device, captured_at, current_path, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    filename,
                    original_path,
                    device,
                    captured_at.isoformat() if captured_at else None,
                    current_path,
                    source,
                ),
            )
            await conn.commit()
            capture_id = cursor.lastrowid
            logger.debug(f"Inserted capture: id={capture_id}, filename={filename}, source={source}")
            return capture_id

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
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE captures
                SET status = ?, last_error = ?, last_attempt_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error, now, now, capture_id),
            )
            await conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.debug(f"Updated capture {capture_id} status to {status}")
            return updated

    async def get_pending_captures(self) -> list[CaptureRow]:
        """Get all captures with pending status.

        Returns:
            List of CaptureRow objects with status='pending'
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM captures
                WHERE status = 'pending'
                ORDER BY created_at ASC
                """
            )
            rows = await cursor.fetchall()
            return [CaptureRow.from_row(dict(row)) for row in rows]

    async def get_capture_by_id(self, capture_id: int) -> Optional[CaptureRow]:
        """Get a capture by ID.

        Args:
            capture_id: ID of the capture to retrieve

        Returns:
            CaptureRow if found, None otherwise
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM captures WHERE id = ?",
                (capture_id,),
            )
            row = await cursor.fetchone()
            if row:
                return CaptureRow.from_row(dict(row))
            return None

    async def get_capture_by_filename(self, filename: str) -> Optional[CaptureRow]:
        """Get a capture by filename.

        Args:
            filename: Filename to search for

        Returns:
            CaptureRow if found, None otherwise
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM captures WHERE filename = ?",
                (filename,),
            )
            row = await cursor.fetchone()
            if row:
                return CaptureRow.from_row(dict(row))
            return None

    async def increment_retry(self, capture_id: int) -> int:
        """Increment retry count for a capture.

        Args:
            capture_id: ID of the capture

        Returns:
            New retry count

        Raises:
            ValueError: If capture not found
        """
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE captures
                SET retry_count = retry_count + 1, last_attempt_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, capture_id),
            )
            await conn.commit()

            if cursor.rowcount == 0:
                raise ValueError(f"Capture not found: {capture_id}")

            # Get the new retry count
            cursor = await conn.execute(
                "SELECT retry_count FROM captures WHERE id = ?",
                (capture_id,),
            )
            row = await cursor.fetchone()
            new_count = row["retry_count"]
            logger.debug(f"Incremented retry count for capture {capture_id} to {new_count}")
            return new_count

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
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE captures
                SET transcript = ?, transcript_duration_seconds = ?, transcript_language = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (transcript, duration, language, now, capture_id),
            )
            await conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.debug(f"Updated transcription for capture {capture_id}")
            return updated

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
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE captures
                SET template_name = ?, classification_confidence = ?,
                    extracted_fields = ?, suggested_title = ?, tags = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    template,
                    confidence,
                    json.dumps(fields),
                    title,
                    json.dumps(tags),
                    now,
                    capture_id,
                ),
            )
            await conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.debug(f"Updated classification for capture {capture_id}: {template}")
            return updated

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
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE captures
                SET notion_page_id = ?, notion_page_url = ?, updated_at = ?
                WHERE id = ?
                """,
                (page_id, page_url, now, capture_id),
            )
            await conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.debug(f"Updated Notion result for capture {capture_id}: {page_id}")
            return updated

    async def mark_complete(self, capture_id: int) -> bool:
        """Mark a capture as complete.

        Sets status to 'complete' and records completion timestamp.

        Args:
            capture_id: ID of the capture

        Returns:
            True if update succeeded, False if capture not found
        """
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE captures
                SET status = 'complete', completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, capture_id),
            )
            await conn.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info(f"Capture {capture_id} marked complete")
            return updated

    async def update_current_path(self, capture_id: int, current_path: str) -> bool:
        """Update the current path of a capture file.

        Args:
            capture_id: ID of the capture
            current_path: New file path

        Returns:
            True if update succeeded, False if capture not found
        """
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE captures
                SET current_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (current_path, now, capture_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def get_captures_by_status(self, status: str) -> list[CaptureRow]:
        """Get all captures with a specific status.

        Args:
            status: Status to filter by

        Returns:
            List of CaptureRow objects
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM captures
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (status,),
            )
            rows = await cursor.fetchall()
            return [CaptureRow.from_row(dict(row)) for row in rows]

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
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM captures
                WHERE captured_at >= ? AND captured_at <= ?
                ORDER BY captured_at ASC
                """,
                (start_date.isoformat(), end_date.isoformat()),
            )
            rows = await cursor.fetchall()
            return [CaptureRow.from_row(dict(row)) for row in rows]

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
        async with self._get_connection() as conn:
            if status:
                cursor = await conn.execute(
                    """
                    SELECT * FROM captures
                    WHERE source = ? AND status = ?
                    ORDER BY created_at DESC
                    """,
                    (source, status),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT * FROM captures
                    WHERE source = ?
                    ORDER BY created_at DESC
                    """,
                    (source,),
                )
            rows = await cursor.fetchall()
            return [CaptureRow.from_row(dict(row)) for row in rows]

    async def get_source_stats(
        self,
        hours: int = 24,
    ) -> dict[str, dict[str, int]]:
        """Get capture statistics grouped by source.

        Args:
            hours: Number of hours to look back (default 24)

        Returns:
            Dict mapping source to status counts, e.g.:
            {
                'watcher': {'pending': 0, 'complete': 5, 'failed': 1},
                'http': {'pending': 1, 'complete': 10, 'failed': 0}
            }
        """
        async with self._get_connection() as conn:
            # Get counts grouped by source and status for recent captures
            cursor = await conn.execute(
                """
                SELECT
                    COALESCE(source, 'watcher') as source,
                    status,
                    COUNT(*) as count
                FROM captures
                WHERE created_at >= datetime('now', ?)
                GROUP BY source, status
                """,
                (f"-{hours} hours",),
            )
            rows = await cursor.fetchall()

            # Build result dict
            result: dict[str, dict[str, int]] = {
                "watcher": {},
                "http": {},
            }
            for row in rows:
                source = row["source"] or "watcher"
                if source not in result:
                    result[source] = {}
                result[source][row["status"]] = row["count"]

            return result

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
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM captures
                WHERE source = 'http'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [CaptureRow.from_row(dict(row)) for row in rows]

    # =========================================================================
    # Failure Log Operations
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
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO failure_log (capture_id, stage, error_type, error_message, error_details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    stage,
                    error_type,
                    error_message,
                    json.dumps(error_details) if error_details else None,
                ),
            )
            await conn.commit()
            log_id = cursor.lastrowid
            logger.warning(
                f"Logged failure for capture {capture_id}: stage={stage}, error={error_message}"
            )
            return log_id

    async def get_failures_for_capture(self, capture_id: int) -> list[FailureLogRow]:
        """Get all failure log entries for a capture.

        Args:
            capture_id: ID of the capture

        Returns:
            List of FailureLogRow objects, ordered by occurrence time
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM failure_log
                WHERE capture_id = ?
                ORDER BY occurred_at ASC
                """,
                (capture_id,),
            )
            rows = await cursor.fetchall()
            return [FailureLogRow.from_row(dict(row)) for row in rows]

    # =========================================================================
    # Daily Stats Operations
    # =========================================================================

    async def get_daily_stats(self, date: str) -> Optional[DailyStatsRow]:
        """Get statistics for a specific date.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            DailyStatsRow if found, None otherwise
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM daily_stats WHERE date = ?",
                (date,),
            )
            row = await cursor.fetchone()
            if row:
                return DailyStatsRow.from_row(dict(row))
            return None

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
        # Get existing stats to merge with updates
        existing = await self.get_daily_stats(date)

        values = {
            "date": date,
            "captures_received": captures_received
            if captures_received is not None
            else (existing.captures_received if existing else 0),
            "captures_completed": captures_completed
            if captures_completed is not None
            else (existing.captures_completed if existing else 0),
            "captures_failed": captures_failed
            if captures_failed is not None
            else (existing.captures_failed if existing else 0),
            "total_audio_seconds": total_audio_seconds
            if total_audio_seconds is not None
            else (existing.total_audio_seconds if existing else 0.0),
            "avg_processing_time_seconds": avg_processing_time_seconds
            if avg_processing_time_seconds is not None
            else (existing.avg_processing_time_seconds if existing else None),
            "template_breakdown": json.dumps(template_breakdown)
            if template_breakdown is not None
            else (json.dumps(existing.template_breakdown) if existing and existing.template_breakdown else None),
        }

        async with self._get_connection() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO daily_stats
                (date, captures_received, captures_completed, captures_failed,
                 total_audio_seconds, avg_processing_time_seconds, template_breakdown)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["date"],
                    values["captures_received"],
                    values["captures_completed"],
                    values["captures_failed"],
                    values["total_audio_seconds"],
                    values["avg_processing_time_seconds"],
                    values["template_breakdown"],
                ),
            )
            await conn.commit()
            logger.debug(f"Updated daily stats for {date}")
            return True

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
        valid_fields = {"captures_received", "captures_completed", "captures_failed"}
        if field not in valid_fields:
            raise ValueError(f"Invalid field: {field}. Must be one of {valid_fields}")

        async with self._get_connection() as conn:
            # Ensure row exists
            await conn.execute(
                """
                INSERT OR IGNORE INTO daily_stats (date)
                VALUES (?)
                """,
                (date,),
            )

            # Increment atomically
            await conn.execute(
                f"""
                UPDATE daily_stats
                SET {field} = {field} + ?
                WHERE date = ?
                """,
                (amount, date),
            )
            await conn.commit()

            # Get new value
            cursor = await conn.execute(
                f"SELECT {field} FROM daily_stats WHERE date = ?",
                (date,),
            )
            row = await cursor.fetchone()
            return row[field]

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
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM daily_stats
                WHERE date >= ? AND date <= ?
                ORDER BY date ASC
                """,
                (start_date, end_date),
            )
            rows = await cursor.fetchall()
            return [DailyStatsRow.from_row(dict(row)) for row in rows]

    # =========================================================================
    # Utility Operations
    # =========================================================================

    async def reset_capture(self, capture_id: int) -> bool:
        """Reset a capture to pending status for reprocessing.

        Clears error state and resets retry count.

        Args:
            capture_id: ID of the capture to reset

        Returns:
            True if reset succeeded, False if capture not found
        """
        now = datetime.utcnow().isoformat()

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE captures
                SET status = 'pending', retry_count = 0, last_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, capture_id),
            )
            await conn.commit()
            reset = cursor.rowcount > 0
            if reset:
                logger.info(f"Reset capture {capture_id} to pending")
            return reset

    async def get_queue_depth(self) -> dict[str, int]:
        """Get count of captures by status.

        Returns:
            Dictionary mapping status to count
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM captures
                GROUP BY status
                """
            )
            rows = await cursor.fetchall()
            return {row["status"]: row["count"] for row in rows}

    async def delete_capture(self, capture_id: int) -> bool:
        """Delete a capture and its failure logs.

        Args:
            capture_id: ID of the capture to delete

        Returns:
            True if deletion succeeded, False if capture not found
        """
        async with self._get_connection() as conn:
            # Delete failure logs first (foreign key constraint)
            await conn.execute(
                "DELETE FROM failure_log WHERE capture_id = ?",
                (capture_id,),
            )

            # Delete capture
            cursor = await conn.execute(
                "DELETE FROM captures WHERE id = ?",
                (capture_id,),
            )
            await conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted capture {capture_id}")
            return deleted
