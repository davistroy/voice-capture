"""Folder watcher service for Voice Capture.

Monitors the inbox directory for new audio files, validates them,
and queues them for processing.
"""

from src.watcher.file_validator import (
    AudioFormat,
    FileValidationError,
    FileValidator,
    ValidationResult,
)
from src.watcher.watcher import FolderWatcher, WatcherCallback, WatcherError

__all__ = [
    "AudioFormat",
    "FileValidationError",
    "FileValidator",
    "FolderWatcher",
    "ValidationResult",
    "WatcherCallback",
    "WatcherError",
]
