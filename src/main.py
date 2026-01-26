"""Main application entry point for Voice Capture.

Initializes all services, starts the folder watcher, and runs the
processing loop. Handles graceful shutdown on SIGTERM/SIGINT.

Usage:
    python -m src.main

Docker entrypoint:
    CMD ["python", "-m", "src.main"]
"""

import asyncio
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from src.classification.classification import ClassificationService
from src.classification.template_loader import TemplateLoader
from src.config.settings import get_settings, Settings
from src.db.database import Database
from src.http.server import HttpUploadServer
from src.notion.client import NotionService
from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.retry import RetryConfig
from src.transcription.service import TranscriptionService
from src.watcher.watcher import FolderWatcher, NewCaptureEvent


logger = logging.getLogger(__name__)


def setup_logging(settings: Settings) -> None:
    """Configure logging per TDD Section 10.1 format.

    Log format: 2026-01-20 14:30:22 | INFO | watcher | New file detected: ...

    Args:
        settings: Application settings with logging configuration.
    """
    log_format = settings.logging.format
    log_level = getattr(logging, settings.logging.level.upper(), logging.INFO)

    # Create formatters
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    # File handler with rotation (if logs directory exists)
    file_handler: Optional[RotatingFileHandler] = None
    if settings.paths.logs.exists() or settings.paths.logs.parent.exists():
        settings.paths.logs.mkdir(parents=True, exist_ok=True)
        log_file = settings.paths.logs / "voice_capture.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=settings.logging.max_bytes,
            backupCount=settings.logging.backup_count,
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    if file_handler:
        root_logger.addHandler(file_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("watchdog").setLevel(logging.INFO)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("notion_client").setLevel(logging.WARNING)

    logger.info("Logging configured: level=%s, file=%s",
                settings.logging.level,
                log_file if file_handler else "console only")


class VoiceCaptureApp:
    """Main application orchestrating all voice capture services.

    Initializes and manages:
    - Database connection
    - Transcription service (Whisper API)
    - Notion integration
    - Folder watcher
    - Pipeline orchestrator

    Handles graceful shutdown preserving in-progress work.
    """

    def __init__(self, settings: Settings):
        """Initialize application with settings.

        Args:
            settings: Application configuration.
        """
        self.settings = settings
        self._db: Optional[Database] = None
        self._transcription: Optional[TranscriptionService] = None
        self._notion: Optional[NotionService] = None
        self._watcher: Optional[FolderWatcher] = None
        self._orchestrator: Optional[PipelineOrchestrator] = None
        self._http_server: Optional[HttpUploadServer] = None
        self._shutdown_event = asyncio.Event()
        self._processing_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize all services with dependency injection.

        Creates and connects all required services:
        1. Database - SQLite with async connection pool
        2. Transcription - Whisper API with retry logic
        3. Notion - Page creation with retry logic
        4. Pipeline - Orchestrates processing flow
        5. Watcher - Monitors inbox for new files

        Raises:
            RuntimeError: If required configuration is missing.
        """
        logger.info("Initializing Voice Capture application...")

        # Validate required configuration
        missing = self.settings.validate_required_for_production()
        if missing:
            error_msg = f"Missing required configuration: {', '.join(missing)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Ensure directories exist
        self.settings.ensure_directories_exist()
        logger.info("Directories verified: inbox=%s, processing=%s, failed=%s",
                    self.settings.paths.inbox,
                    self.settings.paths.processing,
                    self.settings.paths.failed)

        # Initialize database
        self._db = Database(self.settings.paths.database)
        await self._db.initialize()
        logger.info("Database initialized: %s", self.settings.paths.database)

        # Initialize transcription service using factory method
        self._transcription = TranscriptionService.from_settings(self.settings)
        logger.info("Transcription service initialized: backend=%s, model=%s",
                    self._transcription.backend_name,
                    self.settings.transcription.model)

        # Initialize Notion service using factory method
        self._notion = NotionService.from_settings(self.settings)
        logger.info("Notion service initialized: database=%s",
                    self.settings.notion_voice_captures_db_id[:8] + "...")

        # Initialize classification service (Phase 2)
        classification = ClassificationService.from_settings(self.settings)
        template_loader = classification.template_loader
        logger.info("Classification service initialized: model=%s, templates=%d",
                    classification.config.model,
                    len(template_loader.templates))

        # Initialize pipeline orchestrator
        retry_config = RetryConfig(
            max_retries=self.settings.pipeline.max_retries,
            base_backoff_seconds=self.settings.pipeline.base_backoff_seconds,
            max_backoff_seconds=self.settings.pipeline.max_backoff_seconds,
        )

        self._orchestrator = PipelineOrchestrator(
            db=self._db,
            transcription=self._transcription,
            notion=self._notion,
            retry_config=retry_config,
            failed_path=self.settings.paths.failed,
            classification=classification,
            template_loader=template_loader,
        )
        logger.info("Pipeline orchestrator initialized")

        # Initialize folder watcher
        self._watcher = FolderWatcher(
            inbox_path=self.settings.paths.inbox,
            processing_path=self.settings.paths.processing,
            failed_path=self.settings.paths.failed,
            db=self._db,
            file_settle_delay=self.settings.pipeline.file_settle_delay_seconds,
            valid_extensions=tuple(self.settings.watcher.valid_extensions),
            max_file_size_mb=self.settings.audio.max_size_mb,
        )

        # Register callback to process new captures
        self._watcher.on_new_capture(self._on_new_capture)
        logger.info("Folder watcher initialized: watching=%s", self.settings.paths.inbox)

        # Initialize HTTP server if enabled
        if self.settings.http.enabled:
            self._http_server = HttpUploadServer(
                settings=self.settings.http,
                paths=self.settings.paths,
                db=self._db,
                file_validator=self._watcher.file_validator,
                orchestrator=self._orchestrator,
            )
            logger.info("HTTP upload server initialized: host=%s, port=%d, auth=%s",
                        self.settings.http.host,
                        self.settings.http.port,
                        "enabled" if self.settings.http.api_key else "disabled")
        else:
            logger.info("HTTP upload server: disabled")

        logger.info("All services initialized successfully")

    async def _on_new_capture(self, event: NewCaptureEvent) -> None:
        """Handle new capture event from watcher.

        Triggers immediate processing of the new capture.

        Args:
            event: New capture event with file details.
        """
        logger.info("New capture detected: id=%d, file=%s, device=%s",
                    event.capture_id, event.filename, event.device.value)

        # Process the capture immediately
        if self._orchestrator:
            try:
                result = await self._orchestrator.process_capture(event.capture_id)
                if result.success:
                    logger.info("Capture %d processed successfully: notion_url=%s",
                                event.capture_id, result.notion_page_url)
                else:
                    logger.warning("Capture %d processing failed: %s (stage=%s)",
                                   event.capture_id, result.error, result.stage)
            except Exception as e:
                logger.error("Error processing capture %d: %s", event.capture_id, e)

    async def run(self) -> None:
        """Run the main application loop.

        Starts the folder watcher and HTTP server (if enabled), processes pending items.
        Runs until shutdown signal is received.
        """
        if not self._watcher or not self._orchestrator:
            raise RuntimeError("Application not initialized. Call initialize() first.")

        logger.info("Starting Voice Capture application...")

        # Start folder watcher
        await self._watcher.start()
        logger.info("Folder watcher started")

        # Start HTTP server if enabled
        if self._http_server:
            await self._http_server.start()
            logger.info("HTTP upload server listening on http://%s:%d",
                        self.settings.http.host,
                        self.settings.http.port)

        # Process any pending items from previous runs
        await self._process_pending_on_startup()

        # Main loop - wait for shutdown signal
        logger.info("Application running. Press Ctrl+C to stop.")
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("Received cancellation signal")

        logger.info("Shutting down...")

    async def _process_pending_on_startup(self) -> None:
        """Process any pending captures from previous runs.

        Handles recovery after service restart by processing
        items that were left in pending or intermediate states.
        """
        if not self._orchestrator or not self._db:
            return

        # Get counts of items in various states
        queue_depth = await self._db.get_queue_depth()
        pending_count = queue_depth.get("pending", 0)
        transcribing_count = queue_depth.get("transcribing", 0)
        classifying_count = queue_depth.get("classifying", 0)
        posting_count = queue_depth.get("posting", 0)

        total_to_process = pending_count + transcribing_count + classifying_count + posting_count

        if total_to_process == 0:
            logger.info("No pending captures to process on startup")
            return

        logger.info("Found %d captures to process on startup: "
                    "pending=%d, transcribing=%d, classifying=%d, posting=%d",
                    total_to_process, pending_count, transcribing_count,
                    classifying_count, posting_count)

        # Reset intermediate states to pending for reprocessing
        # This handles captures that were interrupted mid-processing
        for status in ["transcribing", "classifying", "posting"]:
            captures = await self._db.get_captures_by_status(status)
            for capture in captures:
                logger.info("Resetting interrupted capture %d from %s to pending",
                            capture.id, status)
                await self._db.update_status(capture.id, "pending")

        # Process all pending items
        results = await self._orchestrator.process_pending_queue()

        successful = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)

        logger.info("Startup processing complete: %d successful, %d failed",
                    successful, failed)

    async def shutdown(self) -> None:
        """Gracefully shutdown all services.

        Stops the HTTP server, watcher, waits for in-progress work to complete,
        and closes all connections.
        """
        logger.info("Initiating graceful shutdown...")

        # Signal main loop to stop
        self._shutdown_event.set()

        # Stop HTTP server first (drains in-flight requests)
        if self._http_server:
            logger.info("Stopping HTTP upload server...")
            await self._http_server.stop()

        # Stop folder watcher (prevents new work)
        if self._watcher:
            logger.info("Stopping folder watcher...")
            await self._watcher.stop()

        # Note: We let in-progress processing complete rather than cancelling
        # This preserves work and prevents data loss

        # Close Notion client
        if self._notion:
            logger.info("Closing Notion client...")
            await self._notion.close()

        # Close database connections
        if self._db:
            logger.info("Closing database connections...")
            await self._db.close()

        logger.info("Shutdown complete")


async def main() -> int:
    """Main entry point for the Voice Capture application.

    Loads configuration, initializes services, and runs until
    shutdown signal is received.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    app: Optional[VoiceCaptureApp] = None

    try:
        # Load settings
        settings = get_settings()

        # Setup logging first
        setup_logging(settings)

        logger.info("=" * 60)
        logger.info("Voice Capture to Notion Pipeline")
        logger.info("=" * 60)

        # Create and initialize application
        app = VoiceCaptureApp(settings)

        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()

        def signal_handler(sig: signal.Signals) -> None:
            logger.info("Received signal %s, initiating shutdown...", sig.name)
            if app:
                asyncio.create_task(app.shutdown())

        # Register signal handlers (Unix signals, not available on Windows in all cases)
        try:
            loop.add_signal_handler(signal.SIGTERM, lambda: signal_handler(signal.SIGTERM))
            loop.add_signal_handler(signal.SIGINT, lambda: signal_handler(signal.SIGINT))
        except NotImplementedError:
            # Signal handlers not supported on this platform (Windows)
            logger.warning("Signal handlers not fully supported on this platform")

        # Initialize and run
        await app.initialize()
        await app.run()

        return 0

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        if app:
            await app.shutdown()
        return 0

    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        if app:
            try:
                await app.shutdown()
            except Exception:
                pass
        return 1


def run() -> None:
    """Entry point for running the application.

    Can be called from __main__.py or directly.
    """
    exit_code = asyncio.run(main())
    sys.exit(exit_code)


if __name__ == "__main__":
    run()
