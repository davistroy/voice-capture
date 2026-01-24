"""SQLite database layer for Voice Capture processing state management.

This module provides async database operations using aiosqlite for:
- Processing queue (captures table)
- Failure history (failure_log table)
- Daily statistics (daily_stats table)

The module uses the Repository pattern for organized data access:
- Database: Facade providing backward-compatible interface
- ConnectionPool: Async connection pool management
- Repositories: Specialized classes for each domain entity

Usage:
    # Traditional interface (backward compatible)
    from src.db import Database

    async with Database(path) as db:
        capture_id = await db.insert_capture(...)

    # Repository interface (recommended for new code)
    from src.db import Database

    async with Database(path) as db:
        capture_id = await db.captures.insert(...)
        await db.failures.log(capture_id, "stage", error_message="...")
        await db.statistics.increment(date, "captures_received")
"""

from src.db.connection import ConnectionPool, SCHEMA_SQL, VALID_STATUSES
from src.db.database import Database
from src.db.models import CaptureRow, DailyStatsRow, FailureLogRow
from src.db.repositories import (
    BaseRepository,
    CaptureRepository,
    FailureLogRepository,
    StatisticsRepository,
)

__all__ = [
    # Main facade
    "Database",
    # Connection management
    "ConnectionPool",
    "SCHEMA_SQL",
    "VALID_STATUSES",
    # Data models
    "CaptureRow",
    "DailyStatsRow",
    "FailureLogRow",
    # Repositories
    "BaseRepository",
    "CaptureRepository",
    "FailureLogRepository",
    "StatisticsRepository",
]
