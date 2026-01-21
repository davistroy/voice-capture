"""SQLite database layer for Voice Capture processing state management.

This module provides async database operations using aiosqlite for:
- Processing queue (captures table)
- Failure history (failure_log table)
- Daily statistics (daily_stats table)
"""

from src.db.database import Database
from src.db.models import CaptureRow, FailureLogRow, DailyStatsRow

__all__ = ["Database", "CaptureRow", "FailureLogRow", "DailyStatsRow"]
