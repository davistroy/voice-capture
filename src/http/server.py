"""HTTP upload server for Voice Capture.

Provides an alternative ingestion path for audio files, allowing direct
uploads via iOS Shortcuts over Tailscale instead of going through
Google Drive/rclone.

Routes:
- POST /api/v1/capture - Upload audio file
- GET /api/v1/capture/{id} - Check capture status
- GET /health - Health check endpoint
"""

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from aiohttp import web

from src.config.settings import HttpServerSettings, PathsSettings
from src.db.database import Database
from src.http.middleware import create_middleware_stack
from src.http.responses import ErrorCode, error_response, health_response, success_response
from src.models.capture import Device
from src.watcher.file_validator import FileValidator

if TYPE_CHECKING:
    from src.pipeline.orchestrator import PipelineOrchestrator


logger = logging.getLogger(__name__)


class HttpUploadServer:
    """HTTP server for direct audio file uploads.

    Provides REST API endpoints for:
    - Uploading audio files for processing
    - Checking capture status
    - Health monitoring

    The server runs alongside the folder watcher, providing an alternative
    low-latency path for file ingestion via Tailscale.

    Attributes:
        settings: HTTP server configuration
        paths: Path configuration for file storage
        db: Database for capture records
        file_validator: Validates audio files before processing
        orchestrator: Pipeline orchestrator for processing captures
    """

    def __init__(
        self,
        settings: HttpServerSettings,
        paths: PathsSettings,
        db: Database,
        file_validator: FileValidator,
        orchestrator: "PipelineOrchestrator",
    ) -> None:
        """Initialize HTTP upload server.

        Args:
            settings: HTTP server configuration
            paths: Path configuration (processing directory, etc.)
            db: Database instance for capture records
            file_validator: File validator instance for audio validation
            orchestrator: Pipeline orchestrator for processing uploads
        """
        self.settings = settings
        self.paths = paths
        self.db = db
        self.file_validator = file_validator
        self.orchestrator = orchestrator

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._started = False
        self._start_time: Optional[float] = None

    def _create_app(self) -> web.Application:
        """Create and configure the aiohttp application.

        Returns:
            Configured aiohttp Application with routes and middleware.
        """
        # Create middleware stack with optional authentication
        middlewares = create_middleware_stack(
            api_key=self.settings.api_key,
            skip_auth_paths={"/health"},
        )

        app = web.Application(
            client_max_size=self.settings.max_upload_mb * 1024 * 1024,
            middlewares=middlewares,
        )

        # Store references for handlers
        app["http_server"] = self
        app["settings"] = self.settings
        app["paths"] = self.paths
        app["db"] = self.db
        app["file_validator"] = self.file_validator
        app["orchestrator"] = self.orchestrator

        # Setup routes
        app.router.add_get("/health", self._handle_health)
        app.router.add_post("/api/v1/capture", self._handle_upload)
        app.router.add_get("/api/v1/capture/{capture_id}", self._handle_status)

        # Add startup/shutdown hooks
        app.on_startup.append(self._on_startup)
        app.on_shutdown.append(self._on_shutdown)

        logger.debug("HTTP application created with routes: /health, /api/v1/capture")

        return app

    async def _on_startup(self, app: web.Application) -> None:
        """Handle application startup.

        Args:
            app: The aiohttp application.
        """
        logger.info("HTTP server starting up...")

    async def _on_shutdown(self, app: web.Application) -> None:
        """Handle application shutdown.

        Args:
            app: The aiohttp application.
        """
        logger.info("HTTP server shutting down...")

    async def start(self) -> None:
        """Start the HTTP server.

        Creates the application, sets up the runner, and starts listening
        on the configured host and port.

        Raises:
            RuntimeError: If server is already started or fails to start.
        """
        if self._started:
            raise RuntimeError("HTTP server is already started")

        logger.info(
            "Starting HTTP upload server on %s:%d",
            self.settings.host,
            self.settings.port,
        )

        # Create application
        self._app = self._create_app()

        # Create runner and site
        self._runner = web.AppRunner(
            self._app,
            handle_signals=False,  # Let main app handle signals
        )
        await self._runner.setup()

        self._site = web.TCPSite(
            self._runner,
            self.settings.host,
            self.settings.port,
        )

        try:
            await self._site.start()
            self._started = True
            self._start_time = time.time()
            logger.info(
                "HTTP upload server listening on http://%s:%d",
                self.settings.host,
                self.settings.port,
            )
        except OSError as e:
            logger.error("Failed to start HTTP server: %s", e)
            await self._runner.cleanup()
            raise RuntimeError(f"Failed to start HTTP server: {e}") from e

    async def stop(self) -> None:
        """Stop the HTTP server gracefully.

        Drains existing connections and cleans up resources.
        """
        if not self._started:
            logger.debug("HTTP server not started, nothing to stop")
            return

        logger.info("Stopping HTTP upload server...")

        # Stop accepting new connections
        if self._site:
            await self._site.stop()
            self._site = None

        # Cleanup runner (drains connections)
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        self._app = None
        self._started = False
        self._start_time = None

        logger.info("HTTP upload server stopped")

    @property
    def is_running(self) -> bool:
        """Check if the server is currently running.

        Returns:
            True if server is running, False otherwise.
        """
        return self._started

    @property
    def uptime_seconds(self) -> Optional[float]:
        """Get server uptime in seconds.

        Returns:
            Uptime in seconds if running, None otherwise.
        """
        if self._start_time is None:
            return None
        return time.time() - self._start_time

    # =========================================================================
    # Route Handlers
    # =========================================================================

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /health endpoint.

        Returns server health status including uptime and configuration.

        Args:
            request: The incoming request.

        Returns:
            JSON response with health status.
        """
        uptime = self.uptime_seconds
        details = {
            "host": self.settings.host,
            "port": self.settings.port,
            "max_upload_mb": self.settings.max_upload_mb,
            "auth_enabled": self.settings.api_key is not None,
        }
        if uptime is not None:
            details["uptime_seconds"] = round(uptime, 2)

        return health_response(
            healthy=True,
            http_server="running",
            details=details,
        )

    async def _handle_upload(self, request: web.Request) -> web.Response:
        """Handle POST /api/v1/capture endpoint.

        Receives audio file upload, validates it, saves to processing directory,
        inserts into database, and optionally waits for processing.

        Args:
            request: The incoming request with multipart form data.

        Returns:
            JSON response with capture status or error.
        """
        start_time = time.time()

        # Note: Authentication is handled by middleware

        # Parse query parameters
        wait_for_result = request.query.get("wait", "true").lower() in ("true", "1", "yes")

        # Parse multipart form data
        try:
            reader = await request.multipart()
        except Exception as e:
            logger.warning("Failed to parse multipart data: %s", e)
            return error_response(
                ErrorCode.INVALID_REQUEST,
                "Request must be multipart/form-data",
            )

        # Extract audio file and device
        audio_data: Optional[bytes] = None
        audio_filename: Optional[str] = None
        device_str = "http"

        async for field in reader:
            if field.name == "audio":
                audio_filename = field.filename or "recording.m4a"
                audio_data = await field.read()
            elif field.name == "device":
                device_str = (await field.read()).decode("utf-8").strip().lower()

        if audio_data is None:
            return error_response(
                ErrorCode.MISSING_FILE,
                "No 'audio' field in request",
            )

        # Check file size
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if len(audio_data) > max_bytes:
            return error_response(
                ErrorCode.FILE_TOO_LARGE,
                f"File exceeds maximum size of {self.settings.max_upload_mb}MB",
            )

        # Generate unique filename with timestamp
        from datetime import datetime

        timestamp_str = datetime.utcnow().strftime("%Y-%m-%dT%H%M%S")
        unique_id = uuid.uuid4().hex[:8]

        # Determine extension from original filename
        original_ext = Path(audio_filename).suffix.lower() if audio_filename else ".m4a"
        if original_ext not in (".m4a", ".wav", ".mp3", ".webm"):
            original_ext = ".m4a"  # Default to m4a

        new_filename = f"{timestamp_str}_{device_str}_{unique_id}{original_ext}"

        # Write to temp file first, then move atomically
        temp_path = self.paths.processing / f".tmp_{new_filename}"
        final_path = self.paths.processing / new_filename

        capture_id: Optional[int] = None

        try:
            # Write file atomically
            temp_path.write_bytes(audio_data)

            # Validate the audio file
            validation = self.file_validator.validate_audio_file(temp_path)
            if not validation.is_valid:
                temp_path.unlink(missing_ok=True)
                error_code = ErrorCode.INVALID_AUDIO_FORMAT
                if validation.error_reason == "file_too_large":
                    error_code = ErrorCode.FILE_TOO_LARGE
                return error_response(
                    error_code,
                    validation.error_message or "Invalid audio file",
                )

            # Move to final location
            temp_path.rename(final_path)

            # Parse device
            device = Device.from_string(device_str)

            # Insert into database
            capture_id = await self.db.insert_capture(
                filename=new_filename,
                original_path=str(final_path),
                device=device.value,
                current_path=str(final_path),
                source="http",
            )

            logger.info(
                "HTTP upload received: capture_id=%d, file=%s, device=%s, size=%d bytes",
                capture_id,
                new_filename,
                device.value,
                len(audio_data),
            )

            # Process synchronously if requested
            if wait_for_result:
                result = await self.orchestrator.process_capture(capture_id)
                processing_time_ms = int((time.time() - start_time) * 1000)

                if result.success:
                    return success_response(
                        capture_id=capture_id,
                        status="complete",
                        template=result.template_name,
                        notion_url=result.notion_page_url,
                        processing_time_ms=processing_time_ms,
                    )
                else:
                    return error_response(
                        ErrorCode.PROCESSING_FAILED,
                        result.error or "Processing failed",
                        capture_id=capture_id,
                        extra={"stage": result.stage},
                    )
            else:
                # Return immediately with pending status
                return success_response(
                    capture_id=capture_id,
                    status="pending",
                )

        except Exception as e:
            # Cleanup on failure
            temp_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)

            # Remove database entry if created
            if capture_id is not None:
                try:
                    await self.db.update_status(capture_id, "failed", str(e))
                except Exception:
                    pass

            logger.error("Upload processing failed: %s", e, exc_info=True)
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                f"Upload processing failed: {e}",
                capture_id=capture_id,
            )

    async def _handle_status(self, request: web.Request) -> web.Response:
        """Handle GET /api/v1/capture/{capture_id} endpoint.

        Returns the current status of a capture.

        Args:
            request: The incoming request with capture_id path parameter.

        Returns:
            JSON response with capture status or error.
        """
        # Note: Authentication is handled by middleware

        # Parse capture_id
        try:
            capture_id = int(request.match_info["capture_id"])
        except (KeyError, ValueError):
            return error_response(
                ErrorCode.INVALID_REQUEST,
                "Invalid capture_id",
            )

        # Get capture from database
        capture = await self.db.get_capture_by_id(capture_id)
        if capture is None:
            return error_response(
                ErrorCode.NOT_FOUND,
                f"Capture {capture_id} not found",
            )

        return success_response(
            capture_id=capture_id,
            status=capture.status,
            template=capture.template_name,
            notion_url=capture.notion_page_url,
        )
