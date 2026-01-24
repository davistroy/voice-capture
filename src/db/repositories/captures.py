"""Repository for capture CRUD operations.

Handles all database operations for the captures table including:
- Insert, update, and delete operations
- Status management
- Transcription and classification result storage
- Query operations by various criteria
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from src.db.connection import VALID_STATUSES
from src.db.models import CaptureRow
from src.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class CaptureRepository(BaseRepository):
    """Repository for capture table operations.

    Provides all CRUD operations for managing capture records in the
    processing queue. This includes:
    - Creating new captures
    - Updating status through the processing pipeline
    - Storing transcription and classification results
    - Querying captures by various criteria
    """

    async def insert(
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

    async def get_by_id(self, capture_id: int) -> Optional[CaptureRow]:
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

    async def get_by_filename(self, filename: str) -> Optional[CaptureRow]:
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

    async def get_pending(self) -> list[CaptureRow]:
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

    async def get_by_status(self, status: str) -> list[CaptureRow]:
        """Get all captures with a specific status.

        Args:
            status: Status to filter by

        Returns:
            List of CaptureRow objects

        Raises:
            ValueError: If status is not valid
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

    async def get_by_date_range(
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

    async def get_by_source(
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

    async def get_recent_http_uploads(self, limit: int = 10) -> list[CaptureRow]:
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

    async def get_source_stats(self, hours: int = 24) -> dict[str, dict[str, int]]:
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

    async def reset(self, capture_id: int) -> bool:
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

    async def delete(self, capture_id: int) -> bool:
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
