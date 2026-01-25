"""Unit tests for the HTTP upload server.

Tests cover:
- Server lifecycle (start/stop)
- Health endpoint
- Upload handler (success, validation failures, processing errors)
- Status handler
- Authentication middleware
- Error handling
"""

import asyncio
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import FormData
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from src.config.settings import HttpServerSettings, PathsSettings
from src.http.responses import ErrorCode, error_response, health_response, success_response
from src.http.server import HttpUploadServer
from src.models.capture import Device
from src.watcher.file_validator import AudioFormat, FileValidator, ValidationResult


# ============================================================================
# Response Helper Tests
# ============================================================================


class TestSuccessResponse:
    """Tests for success_response helper."""

    def test_basic_success_response(self):
        """Test minimal success response."""
        response = success_response(capture_id=42, status="pending")
        assert response.status == 200
        # Note: web.json_response returns bytes body, need to decode
        import json

        body = json.loads(response.body)
        assert body["success"] is True
        assert body["capture_id"] == 42
        assert body["status"] == "pending"
        assert "template" not in body
        assert "notion_url" not in body

    def test_full_success_response(self):
        """Test success response with all fields."""
        response = success_response(
            capture_id=42,
            status="complete",
            template="task",
            notion_url="https://notion.so/page-123",
            processing_time_ms=3450,
        )
        import json

        body = json.loads(response.body)
        assert body["success"] is True
        assert body["capture_id"] == 42
        assert body["status"] == "complete"
        assert body["template"] == "task"
        assert body["notion_url"] == "https://notion.so/page-123"
        assert body["processing_time_ms"] == 3450

    def test_success_response_with_extra(self):
        """Test success response with extra fields."""
        response = success_response(
            capture_id=42,
            status="pending",
            extra={"custom_field": "value"},
        )
        import json

        body = json.loads(response.body)
        assert body["custom_field"] == "value"


class TestErrorResponse:
    """Tests for error_response helper."""

    def test_basic_error_response(self):
        """Test minimal error response."""
        response = error_response(
            ErrorCode.INVALID_REQUEST,
            "Bad request",
        )
        import json

        body = json.loads(response.body)
        assert response.status == 400
        assert body["success"] is False
        assert body["error"] == "invalid_request"
        assert body["message"] == "Bad request"
        assert body["capture_id"] is None

    def test_error_response_with_capture_id(self):
        """Test error response with capture_id."""
        response = error_response(
            ErrorCode.PROCESSING_FAILED,
            "Processing failed",
            capture_id=42,
        )
        import json

        body = json.loads(response.body)
        assert response.status == 500
        assert body["capture_id"] == 42

    def test_error_response_status_codes(self):
        """Test correct HTTP status codes for each error type."""
        test_cases = [
            (ErrorCode.INVALID_REQUEST, 400),
            (ErrorCode.INVALID_AUDIO_FORMAT, 400),
            (ErrorCode.FILE_TOO_LARGE, 413),
            (ErrorCode.MISSING_FILE, 400),
            (ErrorCode.AUTHENTICATION_REQUIRED, 401),
            (ErrorCode.AUTHENTICATION_FAILED, 401),
            (ErrorCode.NOT_FOUND, 404),
            (ErrorCode.PROCESSING_FAILED, 500),
            (ErrorCode.INTERNAL_ERROR, 500),
            (ErrorCode.SERVICE_UNAVAILABLE, 503),
        ]
        for error_code, expected_status in test_cases:
            response = error_response(error_code, "Test message")
            assert response.status == expected_status, f"Failed for {error_code}"

    def test_error_response_custom_status(self):
        """Test error response with custom HTTP status."""
        response = error_response(
            ErrorCode.INVALID_REQUEST,
            "Bad request",
            http_status=422,
        )
        assert response.status == 422

    def test_error_response_string_code(self):
        """Test error response with string error code."""
        response = error_response(
            "custom_error",
            "Custom error message",
        )
        import json

        body = json.loads(response.body)
        assert body["error"] == "custom_error"
        assert response.status == 500  # Default status for unknown codes


class TestHealthResponse:
    """Tests for health_response helper."""

    def test_healthy_response(self):
        """Test healthy response."""
        response = health_response(healthy=True)
        import json

        body = json.loads(response.body)
        assert response.status == 200
        assert body["healthy"] is True
        assert body["http_server"] == "running"

    def test_unhealthy_response(self):
        """Test unhealthy response."""
        response = health_response(healthy=False)
        assert response.status == 503

    def test_health_response_with_details(self):
        """Test health response with details."""
        response = health_response(
            healthy=True,
            details={"uptime_seconds": 3600},
        )
        import json

        body = json.loads(response.body)
        assert body["details"]["uptime_seconds"] == 3600


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_http_settings():
    """Create mock HTTP server settings."""
    return HttpServerSettings(
        enabled=True,
        host="127.0.0.1",
        port=9999,  # Use a high port for testing
        api_key=None,
        max_upload_mb=100,
        request_timeout_seconds=60,
    )


@pytest.fixture
def mock_http_settings_with_auth():
    """Create mock HTTP server settings with authentication."""
    return HttpServerSettings(
        enabled=True,
        host="127.0.0.1",
        port=9998,  # Use a high port for testing
        api_key="test-api-key",
        max_upload_mb=100,
        request_timeout_seconds=60,
    )


@pytest.fixture
def mock_paths_settings(tmp_path):
    """Create mock paths settings with temp directories."""
    processing_path = tmp_path / "processing"
    processing_path.mkdir()
    failed_path = tmp_path / "failed"
    failed_path.mkdir()

    settings = MagicMock(spec=PathsSettings)
    settings.processing = processing_path
    settings.failed = failed_path
    return settings


@pytest.fixture
def mock_db():
    """Create mock database."""
    db = AsyncMock()
    db.insert_capture = AsyncMock(return_value=42)
    db.update_status = AsyncMock(return_value=True)
    db.get_capture_by_id = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_file_validator():
    """Create mock file validator that accepts all files."""
    validator = MagicMock(spec=FileValidator)
    validator.validate_audio_file = MagicMock(
        return_value=ValidationResult(
            is_valid=True,
            format=AudioFormat.M4A,
            size_bytes=1000,
        )
    )
    return validator


@pytest.fixture
def mock_orchestrator():
    """Create mock pipeline orchestrator."""

    @dataclass
    class MockProcessingResult:
        success: bool
        template: Optional[str] = None
        notion_page_url: Optional[str] = None
        error: Optional[str] = None
        stage: Optional[str] = None

    orchestrator = AsyncMock()
    orchestrator.process_capture = AsyncMock(
        return_value=MockProcessingResult(
            success=True,
            template="task",
            notion_page_url="https://notion.so/page-123",
        )
    )
    return orchestrator


@pytest.fixture
def sample_audio_bytes():
    """Return minimal valid M4A file header bytes for testing."""
    return bytes(
        [
            0x00,
            0x00,
            0x00,
            0x20,  # Box size (32 bytes)
            0x66,
            0x74,
            0x79,
            0x70,  # "ftyp"
            0x4D,
            0x34,
            0x41,
            0x20,  # "M4A "
            0x00,
            0x00,
            0x00,
            0x00,  # Version
            0x4D,
            0x34,
            0x41,
            0x20,  # "M4A " (compatible brand)
            0x6D,
            0x70,
            0x34,
            0x32,  # "mp42" (compatible brand)
            0x69,
            0x73,
            0x6F,
            0x6D,  # "isom" (compatible brand)
            0x00,
            0x00,
            0x00,
            0x00,  # Padding
        ]
    )


# ============================================================================
# Server Lifecycle Tests
# ============================================================================


class TestHttpUploadServerLifecycle:
    """Tests for HTTP server lifecycle management."""

    @pytest.mark.asyncio
    async def test_server_initialization(
        self,
        mock_http_settings,
        mock_paths_settings,
        mock_db,
        mock_file_validator,
        mock_orchestrator,
    ):
        """Test server can be initialized."""
        server = HttpUploadServer(
            settings=mock_http_settings,
            paths=mock_paths_settings,
            db=mock_db,
            file_validator=mock_file_validator,
            orchestrator=mock_orchestrator,
        )

        assert server.settings == mock_http_settings
        assert not server.is_running
        assert server.uptime_seconds is None

    @pytest.mark.asyncio
    async def test_server_start_stop(
        self,
        mock_http_settings,
        mock_paths_settings,
        mock_db,
        mock_file_validator,
        mock_orchestrator,
    ):
        """Test server can be started and stopped."""
        server = HttpUploadServer(
            settings=mock_http_settings,
            paths=mock_paths_settings,
            db=mock_db,
            file_validator=mock_file_validator,
            orchestrator=mock_orchestrator,
        )

        # Start server
        await server.start()
        assert server.is_running
        assert server.uptime_seconds is not None
        assert server.uptime_seconds >= 0

        # Stop server
        await server.stop()
        assert not server.is_running
        assert server.uptime_seconds is None

    @pytest.mark.asyncio
    async def test_server_double_start_raises(
        self,
        mock_http_settings,
        mock_paths_settings,
        mock_db,
        mock_file_validator,
        mock_orchestrator,
    ):
        """Test starting server twice raises error."""
        server = HttpUploadServer(
            settings=mock_http_settings,
            paths=mock_paths_settings,
            db=mock_db,
            file_validator=mock_file_validator,
            orchestrator=mock_orchestrator,
        )

        await server.start()
        try:
            with pytest.raises(RuntimeError, match="already started"):
                await server.start()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_server_stop_when_not_started(
        self,
        mock_http_settings,
        mock_paths_settings,
        mock_db,
        mock_file_validator,
        mock_orchestrator,
    ):
        """Test stopping server that hasn't started is safe."""
        server = HttpUploadServer(
            settings=mock_http_settings,
            paths=mock_paths_settings,
            db=mock_db,
            file_validator=mock_file_validator,
            orchestrator=mock_orchestrator,
        )

        # Should not raise
        await server.stop()
        assert not server.is_running


# ============================================================================
# HTTP Endpoint Tests using aiohttp test client
# ============================================================================


@pytest.fixture
async def test_client(
    aiohttp_client,
    mock_http_settings,
    mock_paths_settings,
    mock_db,
    mock_file_validator,
    mock_orchestrator,
):
    """Create test client for HTTP server."""
    server = HttpUploadServer(
        settings=mock_http_settings,
        paths=mock_paths_settings,
        db=mock_db,
        file_validator=mock_file_validator,
        orchestrator=mock_orchestrator,
    )
    app = server._create_app()
    return await aiohttp_client(app)


@pytest.fixture
async def test_client_with_auth(
    aiohttp_client,
    mock_http_settings_with_auth,
    mock_paths_settings,
    mock_db,
    mock_file_validator,
    mock_orchestrator,
):
    """Create test client for HTTP server with authentication."""
    server = HttpUploadServer(
        settings=mock_http_settings_with_auth,
        paths=mock_paths_settings,
        db=mock_db,
        file_validator=mock_file_validator,
        orchestrator=mock_orchestrator,
    )
    app = server._create_app()
    return await aiohttp_client(app)


class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_endpoint_returns_ok(self, test_client):
        """Test health endpoint returns 200 OK."""
        resp = await test_client.get("/health")
        assert resp.status == 200

        data = await resp.json()
        assert data["healthy"] is True
        assert data["http_server"] == "running"

    @pytest.mark.asyncio
    async def test_health_endpoint_includes_config(self, test_client):
        """Test health endpoint includes configuration details."""
        resp = await test_client.get("/health")
        data = await resp.json()

        assert "details" in data
        assert "host" in data["details"]
        assert "port" in data["details"]
        assert "max_upload_mb" in data["details"]
        assert "auth_enabled" in data["details"]


class TestUploadEndpoint:
    """Tests for POST /api/v1/capture endpoint."""

    @pytest.mark.asyncio
    async def test_upload_success_sync(self, test_client, sample_audio_bytes, mock_db):
        """Test successful audio upload with sync processing."""
        # Create form data
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )
        form.add_field("device", "watch")

        resp = await test_client.post("/api/v1/capture?wait=true", data=form)
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        assert data["capture_id"] == 42
        assert data["status"] == "complete"
        assert data["template"] == "task"
        assert data["notion_url"] == "https://notion.so/page-123"
        assert "processing_time_ms" in data

    @pytest.mark.asyncio
    async def test_upload_success_async(self, test_client, sample_audio_bytes, mock_db):
        """Test successful audio upload with async processing."""
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )

        resp = await test_client.post("/api/v1/capture?wait=false", data=form)
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        assert data["capture_id"] == 42
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_upload_missing_file(self, test_client, sample_audio_bytes):
        """Test upload without audio file field."""
        # Send empty multipart form with only a text field
        form = FormData()
        form.add_field("device", "watch")
        # Add a dummy binary field that's not named 'audio'
        form.add_field("other", sample_audio_bytes, filename="other.txt")

        resp = await test_client.post("/api/v1/capture", data=form)
        assert resp.status == 400

        data = await resp.json()
        assert data["success"] is False
        assert data["error"] == "missing_file"

    @pytest.mark.asyncio
    async def test_upload_invalid_audio(
        self, test_client, mock_file_validator, sample_audio_bytes
    ):
        """Test upload with invalid audio file."""
        # Configure validator to reject file
        mock_file_validator.validate_audio_file.return_value = ValidationResult(
            is_valid=False,
            format=AudioFormat.UNKNOWN,
            size_bytes=1000,
            error_message="Invalid audio file",
            error_reason="invalid_format",
        )

        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )

        resp = await test_client.post("/api/v1/capture", data=form)
        assert resp.status == 400

        data = await resp.json()
        assert data["success"] is False
        assert data["error"] == "invalid_audio_format"

    @pytest.mark.asyncio
    async def test_upload_processing_failure(
        self, test_client, mock_orchestrator, sample_audio_bytes
    ):
        """Test upload when processing fails."""
        # Configure orchestrator to return failure
        from dataclasses import dataclass

        @dataclass
        class FailedResult:
            success: bool = False
            template: Optional[str] = None
            notion_page_url: Optional[str] = None
            error: str = "Transcription failed"
            stage: str = "transcribing"

        mock_orchestrator.process_capture.return_value = FailedResult()

        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )

        resp = await test_client.post("/api/v1/capture?wait=true", data=form)
        assert resp.status == 500

        data = await resp.json()
        assert data["success"] is False
        assert data["error"] == "processing_failed"
        assert "stage" in data


class TestUploadAuthentication:
    """Tests for upload endpoint authentication."""

    @pytest.mark.asyncio
    async def test_upload_requires_auth(self, test_client_with_auth, sample_audio_bytes):
        """Test upload requires API key when configured."""
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )

        resp = await test_client_with_auth.post("/api/v1/capture", data=form)
        assert resp.status == 401

        data = await resp.json()
        assert data["error"] == "authentication_required"

    @pytest.mark.asyncio
    async def test_upload_invalid_api_key(self, test_client_with_auth, sample_audio_bytes):
        """Test upload with invalid API key."""
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )

        resp = await test_client_with_auth.post(
            "/api/v1/capture",
            data=form,
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status == 401

        data = await resp.json()
        assert data["error"] == "authentication_failed"

    @pytest.mark.asyncio
    async def test_upload_valid_api_key(self, test_client_with_auth, sample_audio_bytes):
        """Test upload with valid API key."""
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )

        resp = await test_client_with_auth.post(
            "/api/v1/capture?wait=true",
            data=form,
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status == 200


class TestStatusEndpoint:
    """Tests for GET /api/v1/capture/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_status_not_found(self, test_client, mock_db):
        """Test status for non-existent capture."""
        mock_db.get_capture_by_id.return_value = None

        resp = await test_client.get("/api/v1/capture/999")
        assert resp.status == 404

        data = await resp.json()
        assert data["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_status_found(self, test_client, mock_db):
        """Test status for existing capture."""
        # Mock capture record
        mock_capture = MagicMock()
        mock_capture.status = "complete"
        mock_capture.template_name = "task"
        mock_capture.notion_page_url = "https://notion.so/page-123"
        mock_db.get_capture_by_id.return_value = mock_capture

        resp = await test_client.get("/api/v1/capture/42")
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        assert data["capture_id"] == 42
        assert data["status"] == "complete"
        assert data["template"] == "task"
        assert data["notion_url"] == "https://notion.so/page-123"

    @pytest.mark.asyncio
    async def test_status_invalid_id(self, test_client):
        """Test status with invalid capture ID."""
        resp = await test_client.get("/api/v1/capture/invalid")
        assert resp.status == 400

        data = await resp.json()
        assert data["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_status_requires_auth(self, test_client_with_auth, mock_db):
        """Test status requires API key when configured."""
        resp = await test_client_with_auth.get("/api/v1/capture/42")
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_status_with_valid_auth(self, test_client_with_auth, mock_db):
        """Test status with valid API key."""
        mock_capture = MagicMock()
        mock_capture.status = "pending"
        mock_capture.template_name = None
        mock_capture.notion_page_url = None
        mock_db.get_capture_by_id.return_value = mock_capture

        resp = await test_client_with_auth.get(
            "/api/v1/capture/42",
            headers={"X-API-Key": "test-api-key"},
        )
        assert resp.status == 200


class TestUploadDeviceHandling:
    """Tests for device field handling in uploads."""

    @pytest.mark.asyncio
    async def test_upload_device_watch(self, test_client, sample_audio_bytes):
        """Test upload with watch device."""
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )
        form.add_field("device", "watch")

        resp = await test_client.post("/api/v1/capture?wait=true", data=form)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_upload_device_phone(self, test_client, sample_audio_bytes):
        """Test upload with phone device."""
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )
        form.add_field("device", "phone")

        resp = await test_client.post("/api/v1/capture?wait=true", data=form)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_upload_default_device(self, test_client, sample_audio_bytes):
        """Test upload without device defaults to http."""
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )
        # No device field

        resp = await test_client.post("/api/v1/capture?wait=true", data=form)
        assert resp.status == 200


class TestFileExtensionHandling:
    """Tests for file extension handling in uploads."""

    @pytest.mark.asyncio
    async def test_upload_m4a_extension(self, test_client, sample_audio_bytes, mock_db):
        """Test upload with .m4a extension."""
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.m4a",
            content_type="audio/mp4",
        )

        resp = await test_client.post("/api/v1/capture?wait=true", data=form)
        assert resp.status == 200

        # Verify filename was generated with correct extension
        call_args = mock_db.insert_capture.call_args
        assert call_args.kwargs["filename"].endswith(".m4a")

    @pytest.mark.asyncio
    async def test_upload_unknown_extension_defaults_m4a(
        self, test_client, sample_audio_bytes, mock_db
    ):
        """Test upload with unknown extension defaults to .m4a."""
        form = FormData()
        form.add_field(
            "audio",
            sample_audio_bytes,
            filename="recording.unknown",
            content_type="audio/mp4",
        )

        resp = await test_client.post("/api/v1/capture?wait=true", data=form)
        assert resp.status == 200

        call_args = mock_db.insert_capture.call_args
        assert call_args.kwargs["filename"].endswith(".m4a")
