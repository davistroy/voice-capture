"""Repository classes for database operations.

This module provides the repository pattern implementation for the
Voice Capture database layer. Each repository handles operations
for a specific domain entity:

- CaptureRepository: Capture queue management
- FailureLogRepository: Failure history tracking
- StatisticsRepository: Daily statistics aggregation
"""

from src.db.repositories.base import BaseRepository
from src.db.repositories.captures import CaptureRepository
from src.db.repositories.failures import FailureLogRepository
from src.db.repositories.statistics import StatisticsRepository

__all__ = [
    "BaseRepository",
    "CaptureRepository",
    "FailureLogRepository",
    "StatisticsRepository",
]
