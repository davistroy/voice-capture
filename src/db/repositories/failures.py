"""Repository for failure log operations.

Handles all database operations for the failure_log table including:
- Logging processing failures
- Querying failure history for debugging
"""

import json
import logging
from typing import Any, Optional

from src.db.models import FailureLogRow
from src.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class FailureLogRepository(BaseRepository):
    """Repository for failure_log table operations.

    Provides operations for logging and querying processing failures.
    Each failure record is associated with a capture and records:
    - Processing stage where failure occurred
    - Error type and message
    - Additional error details as JSON
    """

    async def log(
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

    async def get_for_capture(self, capture_id: int) -> list[FailureLogRow]:
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

    async def get_recent(self, limit: int = 50) -> list[FailureLogRow]:
        """Get recent failure log entries.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of FailureLogRow objects, most recent first
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM failure_log
                ORDER BY occurred_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [FailureLogRow.from_row(dict(row)) for row in rows]

    async def get_by_stage(self, stage: str, limit: int = 50) -> list[FailureLogRow]:
        """Get failure log entries for a specific stage.

        Args:
            stage: Processing stage to filter by
            limit: Maximum number of entries to return

        Returns:
            List of FailureLogRow objects, most recent first
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM failure_log
                WHERE stage = ?
                ORDER BY occurred_at DESC
                LIMIT ?
                """,
                (stage, limit),
            )
            rows = await cursor.fetchall()
            return [FailureLogRow.from_row(dict(row)) for row in rows]

    async def delete_for_capture(self, capture_id: int) -> int:
        """Delete all failure log entries for a capture.

        Args:
            capture_id: ID of the capture

        Returns:
            Number of entries deleted
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM failure_log WHERE capture_id = ?",
                (capture_id,),
            )
            await conn.commit()
            return cursor.rowcount
