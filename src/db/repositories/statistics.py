"""Repository for daily statistics operations.

Handles all database operations for the daily_stats table including:
- Storing and retrieving daily processing statistics
- Atomic increment operations for counters
- Date range queries for reporting
"""

import json
import logging
from typing import Optional

from src.db.models import DailyStatsRow
from src.db.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class StatisticsRepository(BaseRepository):
    """Repository for daily_stats table operations.

    Provides operations for tracking and querying daily processing
    statistics including:
    - Capture counts (received, completed, failed)
    - Audio duration totals
    - Processing time averages
    - Template usage breakdown
    """

    async def get(self, date: str) -> Optional[DailyStatsRow]:
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

    async def update(
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
        Only updates fields that are explicitly provided; others are preserved.

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
        existing = await self.get(date)

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

    async def increment(
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

        Raises:
            ValueError: If field is not valid for incrementing
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

    async def get_for_date_range(
        self,
        start_date: str,
        end_date: str,
    ) -> list[DailyStatsRow]:
        """Get daily stats for a date range.

        Args:
            start_date: Start date in YYYY-MM-DD format (inclusive)
            end_date: End date in YYYY-MM-DD format (inclusive)

        Returns:
            List of DailyStatsRow objects ordered by date
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

    async def add_audio_duration(self, date: str, duration_seconds: float) -> float:
        """Add audio duration to daily total.

        Args:
            date: Date in YYYY-MM-DD format
            duration_seconds: Duration to add in seconds

        Returns:
            New total audio duration for the day
        """
        async with self._get_connection() as conn:
            # Ensure row exists
            await conn.execute(
                """
                INSERT OR IGNORE INTO daily_stats (date)
                VALUES (?)
                """,
                (date,),
            )

            # Add duration atomically
            await conn.execute(
                """
                UPDATE daily_stats
                SET total_audio_seconds = total_audio_seconds + ?
                WHERE date = ?
                """,
                (duration_seconds, date),
            )
            await conn.commit()

            # Get new value
            cursor = await conn.execute(
                "SELECT total_audio_seconds FROM daily_stats WHERE date = ?",
                (date,),
            )
            row = await cursor.fetchone()
            return row["total_audio_seconds"]

    async def update_template_breakdown(
        self,
        date: str,
        template_name: str,
    ) -> dict[str, int]:
        """Increment template count in daily breakdown.

        Args:
            date: Date in YYYY-MM-DD format
            template_name: Name of the template to increment

        Returns:
            Updated template breakdown dictionary
        """
        # Get current breakdown
        stats = await self.get(date)
        breakdown = stats.template_breakdown if stats and stats.template_breakdown else {}

        # Increment template count
        breakdown[template_name] = breakdown.get(template_name, 0) + 1

        # Update
        await self.update(date, template_breakdown=breakdown)
        return breakdown
