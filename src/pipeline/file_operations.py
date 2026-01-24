"""File operations for capture processing pipeline.

Extracted from orchestrator.py as part of work item 6.6 to improve
class cohesion and reduce orchestrator complexity.

Provides operations for:
- Moving files to failed directory
- Deleting files on successful processing
- Moving files to processing directory
"""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


logger = logging.getLogger(__name__)


class DatabasePathUpdater(Protocol):
    """Protocol for database path update operations.

    Allows FileOperations to update the database without depending
    on the concrete Database class.
    """

    async def update_current_path(self, capture_id: int, path: str) -> bool:
        """Update the current path for a capture in the database."""
        ...


@dataclass
class PathConfig:
    """Configuration for file operation paths.

    Attributes:
        inbox: Directory for incoming audio files.
        processing: Directory for files being processed.
        failed: Directory for failed files.
    """

    inbox: Path
    processing: Path
    failed: Path


class FileOperations:
    """File operations for capture processing pipeline.

    Handles file movement and deletion operations used during
    voice capture processing. Operations are designed to be
    resilient to missing files and handle edge cases gracefully.

    Args:
        paths: Path configuration for file operations.
        db: Optional database instance for updating file paths.
             If not provided, path updates will be logged but not persisted.
    """

    def __init__(
        self,
        paths: PathConfig,
        db: Optional[DatabasePathUpdater] = None,
    ):
        self._paths = paths
        self._db = db

    @classmethod
    def from_failed_path(
        cls,
        failed_path: Path,
        db: Optional[DatabasePathUpdater] = None,
    ) -> "FileOperations":
        """Create FileOperations with just a failed path.

        This factory method supports the existing orchestrator interface
        which only specifies a failed_path.

        Args:
            failed_path: Directory for failed files.
            db: Optional database instance.

        Returns:
            FileOperations instance.
        """
        return cls(
            paths=PathConfig(
                inbox=Path("/app/inbox"),
                processing=Path("/app/processing"),
                failed=failed_path,
            ),
            db=db,
        )

    async def move_to_processing(
        self,
        source: Path,
        capture_id: Optional[int] = None,
    ) -> Optional[Path]:
        """Move file from inbox to processing directory.

        Args:
            source: Path to the source file.
            capture_id: Optional capture ID for database update.

        Returns:
            Path to the destination file, or None if move failed.
        """
        if not source.exists():
            logger.warning(f"Cannot move file to processing - file not found: {source}")
            return None

        # Ensure processing directory exists
        self._paths.processing.mkdir(parents=True, exist_ok=True)

        # Determine destination path with conflict handling
        dest_path = self._paths.processing / source.name
        dest_path = self._handle_name_conflict(dest_path)

        try:
            shutil.move(str(source), str(dest_path))
            logger.info(f"Moved file to processing: {dest_path}")

            # Update database if capture_id provided
            if capture_id is not None and self._db is not None:
                await self._db.update_current_path(capture_id, str(dest_path))

            return dest_path

        except Exception as e:
            logger.error(f"Failed to move file to processing {dest_path}: {e}")
            return None

    async def move_to_failed(
        self,
        source: Path,
        capture_id: Optional[int] = None,
    ) -> Optional[Path]:
        """Move file to failed directory.

        Args:
            source: Path to the source file.
            capture_id: Optional capture ID for database update.

        Returns:
            Path to the destination file, or None if move failed.
        """
        if not source.exists():
            logger.warning(f"Cannot move file to failed - file not found: {source}")
            return None

        # Ensure failed directory exists
        self._paths.failed.mkdir(parents=True, exist_ok=True)

        # Move file
        dest_path = self._paths.failed / source.name

        try:
            shutil.move(str(source), str(dest_path))
            logger.info(f"Moved failed file to: {dest_path}")

            # Update database if capture_id provided
            if capture_id is not None and self._db is not None:
                await self._db.update_current_path(capture_id, str(dest_path))

            return dest_path

        except Exception as e:
            logger.error(f"Failed to move file to {dest_path}: {e}")
            return None

    async def delete_on_success(self, file_path: Path) -> bool:
        """Delete file after successful processing.

        Per PRD: Audio deleted on success - files removed from Google Drive
        after successful Notion post.

        Args:
            file_path: Path to the file to delete.

        Returns:
            True if file was deleted, False otherwise.
        """
        if not file_path.exists():
            logger.debug(f"Source file already deleted: {file_path}")
            return True  # Consider already-deleted as success

        try:
            file_path.unlink()
            logger.info(f"Deleted source audio file: {file_path}")
            return True

        except Exception as e:
            # Non-fatal - log but don't fail the operation
            logger.warning(f"Failed to delete source file {file_path}: {e}")
            return False

    def _handle_name_conflict(self, dest_path: Path) -> Path:
        """Handle filename conflicts by appending a counter.

        Args:
            dest_path: The intended destination path.

        Returns:
            A unique destination path that doesn't conflict.
        """
        if not dest_path.exists():
            return dest_path

        base = dest_path.stem
        ext = dest_path.suffix
        counter = 1

        while dest_path.exists():
            dest_path = dest_path.parent / f"{base}_{counter}{ext}"
            counter += 1

        return dest_path

    def is_in_failed_directory(self, file_path: Path) -> bool:
        """Check if a file is in the failed directory.

        Args:
            file_path: Path to check.

        Returns:
            True if the file is in or under the failed directory.
        """
        try:
            return self._paths.failed in file_path.parents or file_path.parent == self._paths.failed
        except (ValueError, TypeError):
            return False

    @property
    def failed_path(self) -> Path:
        """Get the failed directory path."""
        return self._paths.failed

    @property
    def processing_path(self) -> Path:
        """Get the processing directory path."""
        return self._paths.processing

    @property
    def inbox_path(self) -> Path:
        """Get the inbox directory path."""
        return self._paths.inbox
