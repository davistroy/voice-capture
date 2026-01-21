"""Folder watcher service for Voice Capture.

Uses Python watchdog library to monitor the inbox directory for new audio files.
Validates files, parses metadata from filenames, and queues for processing.
"""

import asyncio
import logging
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.db.database import Database
from src.models.capture import Device, ProcessingStatus
from src.watcher.file_validator import FileValidator, ValidationResult, ParsedFilename

logger = logging.getLogger(__name__)


class WatcherError(Exception):
    """Exception raised by the folder watcher."""

    pass


@dataclass
class NewCaptureEvent:
    """Event emitted when a new capture is queued.

    Attributes:
        capture_id: Database ID of the new capture
        filename: Original filename
        file_path: Current path to the file
        device: Source device
        captured_at: Capture timestamp
    """

    capture_id: int
    filename: str
    file_path: Path
    device: Device
    captured_at: datetime


# Type alias for callback functions
WatcherCallback = Callable[[NewCaptureEvent], Awaitable[None]]


class _WatchdogEventHandler(FileSystemEventHandler):
    """Internal watchdog event handler.

    Bridges watchdog's synchronous events to async processing.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        callback: Callable[[Path], None],
        valid_extensions: tuple[str, ...],
    ):
        """Initialize event handler.

        Args:
            loop: Async event loop for scheduling callbacks
            callback: Callback to invoke on file creation
            valid_extensions: Valid file extensions to watch
        """
        super().__init__()
        self._loop = loop
        self._callback = callback
        self._valid_extensions = tuple(ext.lower() for ext in valid_extensions)

    def on_created(self, event: Any) -> None:
        """Handle file creation event.

        Args:
            event: Watchdog file system event
        """
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Quick extension check to avoid unnecessary processing
        if file_path.suffix.lower() not in self._valid_extensions:
            logger.debug(f"Ignoring file with invalid extension: {file_path}")
            return

        logger.debug(f"File created event: {file_path}")

        # Schedule callback on the async event loop
        try:
            self._loop.call_soon_threadsafe(self._callback, file_path)
        except RuntimeError as e:
            logger.error(f"Failed to schedule callback for {file_path}: {e}")


class FolderWatcher:
    """Watches inbox directory for new audio files.

    Implements the TDD Section 4.1 interface:
    - Monitors inbox directory using watchdog
    - Validates audio files (format, size, magic bytes)
    - Parses filenames for metadata
    - Queues files for processing in database
    - Moves files from /inbox/ to /processing/

    Usage:
        watcher = FolderWatcher(
            inbox_path=Path("/app/inbox"),
            processing_path=Path("/app/processing"),
            failed_path=Path("/app/failed"),
            db=database,
        )
        watcher.on_new_capture(my_callback)
        await watcher.start()
        # ... run until shutdown
        await watcher.stop()
    """

    def __init__(
        self,
        inbox_path: Path,
        processing_path: Path,
        failed_path: Path,
        db: Database,
        file_settle_delay: float = 2.0,
        valid_extensions: tuple[str, ...] = (".m4a", ".wav", ".mp3"),
        max_file_size_mb: int = 100,
        stability_check_interval: float = 0.5,
    ):
        """Initialize folder watcher.

        Args:
            inbox_path: Directory to watch for new files
            processing_path: Directory to move files being processed
            failed_path: Directory for invalid/failed files
            db: Database instance for queue operations
            file_settle_delay: Seconds to wait for file write completion
            valid_extensions: Valid audio file extensions
            max_file_size_mb: Maximum file size in megabytes
            stability_check_interval: Interval between file stability checks
        """
        self.inbox_path = inbox_path
        self.processing_path = processing_path
        self.failed_path = failed_path
        self.db = db
        self.file_settle_delay = file_settle_delay
        self.valid_extensions = valid_extensions
        self.stability_check_interval = stability_check_interval

        self._validator = FileValidator(
            valid_extensions=valid_extensions,
            max_size_bytes=max_file_size_mb * 1024 * 1024,
        )

        self._observer: Optional[Observer] = None
        self._running = False
        self._callbacks: list[WatcherCallback] = []
        self._pending_files: Dict[Path, asyncio.Task] = {}
        self._processed_files: Set[str] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def on_new_capture(self, callback: WatcherCallback) -> None:
        """Register callback for new capture events.

        Callbacks are invoked asynchronously when a file is successfully
        validated and queued for processing.

        Args:
            callback: Async function to call with NewCaptureEvent
        """
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start watching for new files.

        Creates required directories, starts the watchdog observer,
        and processes any existing files in the inbox.

        Raises:
            WatcherError: If watcher is already running or cannot start
        """
        if self._running:
            raise WatcherError("Watcher is already running")

        # Store event loop for thread-safe callbacks
        self._loop = asyncio.get_running_loop()

        # Ensure directories exist
        await self._ensure_directories()

        # Create watchdog observer
        self._observer = Observer()
        handler = _WatchdogEventHandler(
            loop=self._loop,
            callback=self._on_file_created_sync,
            valid_extensions=self.valid_extensions,
        )

        self._observer.schedule(handler, str(self.inbox_path), recursive=False)
        self._observer.start()
        self._running = True

        logger.info(f"Started watching {self.inbox_path}")

        # Process any existing files in inbox
        await self._process_existing_files()

    async def stop(self) -> None:
        """Stop watching and cleanup.

        Waits for pending file processing to complete.
        """
        if not self._running:
            return

        self._running = False

        # Cancel pending file processing tasks
        for task in self._pending_files.values():
            task.cancel()

        # Wait for tasks to complete
        if self._pending_files:
            await asyncio.gather(*self._pending_files.values(), return_exceptions=True)
        self._pending_files.clear()

        # Stop observer
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        logger.info("Watcher stopped")

    async def _ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        for directory in [self.inbox_path, self.processing_path, self.failed_path]:
            directory.mkdir(parents=True, exist_ok=True)

    async def _process_existing_files(self) -> None:
        """Process any existing files in the inbox directory."""
        try:
            for file_path in self.inbox_path.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in self.valid_extensions:
                    logger.info(f"Processing existing file: {file_path}")
                    # Use a short delay for existing files (they're already fully written)
                    await self.on_file_created(file_path, settle_delay=0.5)
        except OSError as e:
            logger.error(f"Error scanning inbox directory: {e}")

    def _on_file_created_sync(self, file_path: Path) -> None:
        """Synchronous callback from watchdog (called from observer thread).

        Schedules async processing on the event loop.

        Args:
            file_path: Path to the created file
        """
        with self._lock:
            if not self._running or self._loop is None:
                return

            # Avoid duplicate processing
            if file_path.name in self._processed_files:
                logger.debug(f"Skipping already processed file: {file_path}")
                return

            if file_path in self._pending_files:
                logger.debug(f"Skipping file already being processed: {file_path}")
                return

            # Schedule async processing
            future = asyncio.run_coroutine_threadsafe(
                self.on_file_created(file_path), self._loop
            )
            # Track pending task (we won't actually use the future, just for tracking)
            logger.debug(f"Scheduled processing for: {file_path}")

    async def on_file_created(
        self, file_path: Path, settle_delay: Optional[float] = None
    ) -> None:
        """Handle new file detection.

        Waits for file to settle, validates, parses metadata,
        queues in database, and moves to processing directory.

        Args:
            file_path: Path to the new file
            settle_delay: Override settle delay (uses default if None)
        """
        if settle_delay is None:
            settle_delay = self.file_settle_delay

        # Track this file as pending
        task = asyncio.current_task()
        if task:
            self._pending_files[file_path] = task

        try:
            # Wait for file to settle (finish writing)
            is_stable = await self._wait_for_file_stable(file_path, settle_delay)
            if not is_stable:
                logger.warning(f"File not stable after settle delay: {file_path}")
                # Still try to process it

            # Check if file still exists (might have been moved/deleted)
            if not file_path.exists():
                logger.debug(f"File no longer exists: {file_path}")
                return

            # Validate the file
            validation = self._validator.validate_audio_file(file_path)

            if not validation.is_valid:
                logger.warning(
                    f"Invalid audio file {file_path}: {validation.error_message}"
                )
                await self._move_to_failed(file_path, validation)
                return

            # Parse filename for metadata
            parsed = self._validator.parse_filename(file_path.name, file_path)

            # Check if file already exists in database (duplicate detection)
            existing = await self.db.get_capture_by_filename(file_path.name)
            if existing:
                logger.info(f"File already in database: {file_path.name}")
                # Move file anyway (cleanup)
                try:
                    file_path.unlink()
                except OSError:
                    pass
                return

            # Move to processing directory
            dest_path = await self._move_to_processing(file_path)
            if dest_path is None:
                return

            # Insert into database
            capture_id = await self._insert_capture(
                filename=file_path.name,
                original_path=str(file_path),
                current_path=str(dest_path),
                device=parsed.device,
                captured_at=parsed.timestamp,
            )

            # Mark as processed
            self._processed_files.add(file_path.name)

            # Emit event to callbacks
            event = NewCaptureEvent(
                capture_id=capture_id,
                filename=file_path.name,
                file_path=dest_path,
                device=parsed.device,
                captured_at=parsed.timestamp,
            )

            await self._emit_event(event)

            logger.info(
                f"Queued capture: id={capture_id}, file={file_path.name}, "
                f"device={parsed.device.value}, parsed={parsed.was_parsed}"
            )

        except asyncio.CancelledError:
            logger.debug(f"Processing cancelled for: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}", exc_info=True)
            # Try to move to failed directory
            try:
                await self._move_to_failed(
                    file_path,
                    ValidationResult(
                        is_valid=False,
                        format=self._validator._extension_to_format(file_path.suffix),
                        size_bytes=file_path.stat().st_size if file_path.exists() else 0,
                        error_message=str(e),
                        error_reason="processing_error",
                    ),
                )
            except Exception:
                pass
        finally:
            # Remove from pending
            self._pending_files.pop(file_path, None)

    async def _wait_for_file_stable(self, file_path: Path, max_wait: float) -> bool:
        """Wait for file to become stable (size not changing).

        Args:
            file_path: Path to the file
            max_wait: Maximum time to wait in seconds

        Returns:
            True if file is stable, False if timeout
        """
        elapsed = 0.0
        previous_size: Optional[int] = None

        while elapsed < max_wait:
            if not file_path.exists():
                return False

            is_stable, current_size = self._validator.check_file_stable(
                file_path, previous_size
            )

            if is_stable and previous_size is not None:
                return True

            previous_size = current_size
            await asyncio.sleep(self.stability_check_interval)
            elapsed += self.stability_check_interval

        # Final check
        if previous_size is not None:
            is_stable, _ = self._validator.check_file_stable(file_path, previous_size)
            return is_stable

        return False

    async def _move_to_processing(self, file_path: Path) -> Optional[Path]:
        """Move file to processing directory.

        Uses atomic move where possible.

        Args:
            file_path: Source file path

        Returns:
            Destination path if successful, None if failed
        """
        dest_path = self.processing_path / file_path.name

        try:
            # Handle existing file at destination
            if dest_path.exists():
                # Generate unique name
                base = file_path.stem
                ext = file_path.suffix
                counter = 1
                while dest_path.exists():
                    dest_path = self.processing_path / f"{base}_{counter}{ext}"
                    counter += 1

            # Move file (atomic on same filesystem)
            shutil.move(str(file_path), str(dest_path))
            logger.debug(f"Moved {file_path} to {dest_path}")
            return dest_path

        except OSError as e:
            logger.error(f"Failed to move file {file_path} to processing: {e}")
            return None

    async def _move_to_failed(
        self, file_path: Path, validation: ValidationResult
    ) -> Optional[Path]:
        """Move file to failed directory.

        Args:
            file_path: Source file path
            validation: Validation result with error details

        Returns:
            Destination path if successful, None if failed
        """
        if not file_path.exists():
            return None

        dest_path = self.failed_path / file_path.name

        try:
            # Handle existing file at destination
            if dest_path.exists():
                base = file_path.stem
                ext = file_path.suffix
                counter = 1
                while dest_path.exists():
                    dest_path = self.failed_path / f"{base}_{counter}{ext}"
                    counter += 1

            shutil.move(str(file_path), str(dest_path))

            # Write error info file
            error_file = dest_path.with_suffix(".error")
            error_info = (
                f"Validation failed: {validation.error_reason}\n"
                f"Error: {validation.error_message}\n"
                f"Format: {validation.format.value}\n"
                f"Size: {validation.size_bytes} bytes\n"
                f"Time: {datetime.utcnow().isoformat()}\n"
            )
            error_file.write_text(error_info)

            logger.info(f"Moved invalid file to {dest_path}")
            return dest_path

        except OSError as e:
            logger.error(f"Failed to move file {file_path} to failed: {e}")
            return None

    async def _insert_capture(
        self,
        filename: str,
        original_path: str,
        current_path: str,
        device: Device,
        captured_at: datetime,
    ) -> int:
        """Insert capture record into database.

        Args:
            filename: Original filename
            original_path: Original file location
            current_path: Current file location
            device: Source device
            captured_at: Capture timestamp

        Returns:
            Database ID of the inserted record
        """
        capture_id = await self.db.insert_capture(
            filename=filename,
            original_path=original_path,
            device=device.value,
            captured_at=captured_at,
            current_path=current_path,
        )

        # Update daily stats
        today = datetime.utcnow().strftime("%Y-%m-%d")
        await self.db.increment_daily_stat(today, "captures_received")

        return capture_id

    async def _emit_event(self, event: NewCaptureEvent) -> None:
        """Emit event to all registered callbacks.

        Args:
            event: The event to emit
        """
        for callback in self._callbacks:
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"Error in watcher callback: {e}", exc_info=True)

    def validate_audio_file(self, file_path: Path) -> bool:
        """Validate file is processable audio.

        Public method matching TDD interface.

        Args:
            file_path: Path to the file

        Returns:
            True if file is valid audio
        """
        result = self._validator.validate_audio_file(file_path)
        return result.is_valid

    def parse_filename(self, filename: str) -> tuple[datetime, Device]:
        """Extract timestamp and device from filename.

        Expected format: {timestamp}_{device}.m4a
        Example: 2026-01-20T143022_watch.m4a

        Args:
            filename: Filename to parse

        Returns:
            Tuple of (timestamp, device)
        """
        parsed = self._validator.parse_filename(filename)
        return parsed.timestamp, parsed.device
