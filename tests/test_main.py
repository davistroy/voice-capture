"""Unit tests for the main application entry point.

Tests cover:
- VoiceCaptureApp initialization
- HTTP server integration when enabled/disabled
- Application lifecycle (start, shutdown)
- Signal handling
"""

import asyncio
import os
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import Settings, reload_settings
from src.main import VoiceCaptureApp, setup_logging


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def test_settings_with_http(temp_dir: Path) -> Settings:
    """Create test settings with HTTP server enabled."""
    # Set environment variables for test settings
    os.environ["OPENAI_API_KEY"] = "test-openai-key"
    os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
    os.environ["NOTION_API_KEY"] = "test-notion-key"
    os.environ["NOTION_VOICE_CAPTURES_DB_ID"] = "test-db-id"
    os.environ["NOTION_WEEKLY_SUMMARIES_DB_ID"] = "test-weekly-db-id"
    os.environ["PUSHOVER_API_TOKEN"] = "test-pushover-token"
    os.environ["PUSHOVER_USER_KEY"] = "test-pushover-user"

    # Use temp directories
    os.environ["VOICE_CAPTURE_INBOX_PATH"] = str(temp_dir / "inbox")
    os.environ["VOICE_CAPTURE_PROCESSING_PATH"] = str(temp_dir / "processing")
    os.environ["VOICE_CAPTURE_FAILED_PATH"] = str(temp_dir / "failed")
    os.environ["VOICE_CAPTURE_DB_PATH"] = str(temp_dir / "data" / "test.db")
    os.environ["VOICE_CAPTURE_LOG_PATH"] = str(temp_dir / "logs")

    # Enable HTTP server
    os.environ["HTTP_ENABLED"] = "true"
    os.environ["HTTP_PORT"] = "19999"  # High port for testing
    os.environ["HTTP_HOST"] = "127.0.0.1"

    # Reload settings to pick up test values
    settings = reload_settings()

    # Ensure directories exist
    settings.ensure_directories_exist()

    yield settings

    # Clean up environment variables
    for key in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "NOTION_API_KEY",
        "NOTION_VOICE_CAPTURES_DB_ID",
        "NOTION_WEEKLY_SUMMARIES_DB_ID",
        "PUSHOVER_API_TOKEN",
        "PUSHOVER_USER_KEY",
        "VOICE_CAPTURE_INBOX_PATH",
        "VOICE_CAPTURE_PROCESSING_PATH",
        "VOICE_CAPTURE_FAILED_PATH",
        "VOICE_CAPTURE_DB_PATH",
        "VOICE_CAPTURE_LOG_PATH",
        "HTTP_ENABLED",
        "HTTP_PORT",
        "HTTP_HOST",
    ]:
        os.environ.pop(key, None)

    # Clear settings cache
    reload_settings()


@pytest.fixture
def test_settings_without_http(temp_dir: Path) -> Settings:
    """Create test settings with HTTP server disabled."""
    # Set environment variables for test settings
    os.environ["OPENAI_API_KEY"] = "test-openai-key"
    os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
    os.environ["NOTION_API_KEY"] = "test-notion-key"
    os.environ["NOTION_VOICE_CAPTURES_DB_ID"] = "test-db-id"
    os.environ["NOTION_WEEKLY_SUMMARIES_DB_ID"] = "test-weekly-db-id"
    os.environ["PUSHOVER_API_TOKEN"] = "test-pushover-token"
    os.environ["PUSHOVER_USER_KEY"] = "test-pushover-user"

    # Use temp directories
    os.environ["VOICE_CAPTURE_INBOX_PATH"] = str(temp_dir / "inbox")
    os.environ["VOICE_CAPTURE_PROCESSING_PATH"] = str(temp_dir / "processing")
    os.environ["VOICE_CAPTURE_FAILED_PATH"] = str(temp_dir / "failed")
    os.environ["VOICE_CAPTURE_DB_PATH"] = str(temp_dir / "data" / "test.db")
    os.environ["VOICE_CAPTURE_LOG_PATH"] = str(temp_dir / "logs")

    # HTTP disabled by default (don't set HTTP_ENABLED)

    # Reload settings to pick up test values
    settings = reload_settings()

    # Ensure directories exist
    settings.ensure_directories_exist()

    yield settings

    # Clean up environment variables
    for key in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "NOTION_API_KEY",
        "NOTION_VOICE_CAPTURES_DB_ID",
        "NOTION_WEEKLY_SUMMARIES_DB_ID",
        "PUSHOVER_API_TOKEN",
        "PUSHOVER_USER_KEY",
        "VOICE_CAPTURE_INBOX_PATH",
        "VOICE_CAPTURE_PROCESSING_PATH",
        "VOICE_CAPTURE_FAILED_PATH",
        "VOICE_CAPTURE_DB_PATH",
        "VOICE_CAPTURE_LOG_PATH",
    ]:
        os.environ.pop(key, None)

    # Clear settings cache
    reload_settings()


# ============================================================================
# VoiceCaptureApp Tests
# ============================================================================


class TestVoiceCaptureAppInitialization:
    """Tests for VoiceCaptureApp initialization."""

    def test_app_creation(self, test_settings_without_http):
        """Test application can be created with settings."""
        app = VoiceCaptureApp(test_settings_without_http)

        assert app.settings == test_settings_without_http
        assert app._db is None
        assert app._transcription is None
        assert app._notion is None
        assert app._watcher is None
        assert app._orchestrator is None
        assert app._http_server is None

    def test_app_creation_with_http_enabled(self, test_settings_with_http):
        """Test application can be created with HTTP settings."""
        app = VoiceCaptureApp(test_settings_with_http)

        assert app.settings.http.enabled is True
        assert app.settings.http.port == 19999
        assert app._http_server is None  # Not initialized until initialize() is called


class TestVoiceCaptureAppInitialize:
    """Tests for VoiceCaptureApp.initialize() method."""

    @pytest.mark.asyncio
    async def test_initialize_without_http(self, test_settings_without_http):
        """Test initialization without HTTP server."""
        app = VoiceCaptureApp(test_settings_without_http)

        # Mock external services
        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion_instance = AsyncMock()
            mock_notion.return_value = mock_notion_instance

            await app.initialize()

            # Verify services are initialized
            assert app._db is not None
            assert app._transcription is not None
            assert app._notion is not None
            assert app._watcher is not None
            assert app._orchestrator is not None
            assert app._http_server is None  # HTTP server should not be initialized

            # Clean up
            await app.shutdown()

    @pytest.mark.asyncio
    async def test_initialize_with_http(self, test_settings_with_http):
        """Test initialization with HTTP server enabled."""
        app = VoiceCaptureApp(test_settings_with_http)

        # Mock external services
        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion_instance = AsyncMock()
            mock_notion.return_value = mock_notion_instance

            await app.initialize()

            # Verify HTTP server is initialized
            assert app._http_server is not None
            assert app._http_server.settings.enabled is True
            assert app._http_server.settings.port == 19999
            assert not app._http_server.is_running  # Not started yet

            # Clean up
            await app.shutdown()

    @pytest.mark.asyncio
    async def test_initialize_with_http_auth(self, temp_dir):
        """Test initialization with HTTP server and API key."""
        # Set up settings with API key
        os.environ["OPENAI_API_KEY"] = "test-openai-key"
        os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
        os.environ["NOTION_API_KEY"] = "test-notion-key"
        os.environ["NOTION_VOICE_CAPTURES_DB_ID"] = "test-db-id"
        os.environ["VOICE_CAPTURE_INBOX_PATH"] = str(temp_dir / "inbox")
        os.environ["VOICE_CAPTURE_PROCESSING_PATH"] = str(temp_dir / "processing")
        os.environ["VOICE_CAPTURE_FAILED_PATH"] = str(temp_dir / "failed")
        os.environ["VOICE_CAPTURE_DB_PATH"] = str(temp_dir / "data" / "test.db")
        os.environ["VOICE_CAPTURE_LOG_PATH"] = str(temp_dir / "logs")
        os.environ["HTTP_ENABLED"] = "true"
        os.environ["HTTP_PORT"] = "19998"
        os.environ["HTTP_API_KEY"] = "test-secret-key"

        try:
            settings = reload_settings()
            settings.ensure_directories_exist()

            app = VoiceCaptureApp(settings)

            with patch("src.main.create_whisper_service") as mock_whisper, \
                 patch("src.main.NotionService") as mock_notion:
                mock_whisper.return_value = MagicMock(backend_name="whisper_api")
                mock_notion.return_value = AsyncMock()

                await app.initialize()

                # Verify HTTP server has API key configured
                assert app._http_server is not None
                assert app._http_server.settings.api_key == "test-secret-key"

                await app.shutdown()
        finally:
            # Clean up environment
            for key in [
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NOTION_API_KEY",
                "NOTION_VOICE_CAPTURES_DB_ID", "VOICE_CAPTURE_INBOX_PATH",
                "VOICE_CAPTURE_PROCESSING_PATH", "VOICE_CAPTURE_FAILED_PATH",
                "VOICE_CAPTURE_DB_PATH", "VOICE_CAPTURE_LOG_PATH",
                "HTTP_ENABLED", "HTTP_PORT", "HTTP_API_KEY",
            ]:
                os.environ.pop(key, None)
            reload_settings()


class TestVoiceCaptureAppRun:
    """Tests for VoiceCaptureApp.run() method."""

    @pytest.mark.asyncio
    async def test_run_without_http(self, test_settings_without_http):
        """Test run without HTTP server."""
        app = VoiceCaptureApp(test_settings_without_http)

        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion.return_value = AsyncMock()

            await app.initialize()

            # Start run in background and trigger shutdown quickly
            async def run_and_shutdown():
                run_task = asyncio.create_task(app.run())
                await asyncio.sleep(0.1)  # Let it start
                await app.shutdown()
                try:
                    await asyncio.wait_for(run_task, timeout=2.0)
                except asyncio.TimeoutError:
                    run_task.cancel()
                    try:
                        await run_task
                    except asyncio.CancelledError:
                        pass

            await run_and_shutdown()

    @pytest.mark.asyncio
    async def test_run_with_http(self, test_settings_with_http):
        """Test run with HTTP server starts the server."""
        app = VoiceCaptureApp(test_settings_with_http)

        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion.return_value = AsyncMock()

            await app.initialize()

            # Start run in background and check HTTP server starts
            async def run_and_check():
                run_task = asyncio.create_task(app.run())
                await asyncio.sleep(0.2)  # Let it start

                # HTTP server should be running
                assert app._http_server is not None
                assert app._http_server.is_running

                await app.shutdown()
                try:
                    await asyncio.wait_for(run_task, timeout=2.0)
                except asyncio.TimeoutError:
                    run_task.cancel()
                    try:
                        await run_task
                    except asyncio.CancelledError:
                        pass

            await run_and_check()

    @pytest.mark.asyncio
    async def test_run_without_initialize_raises(self, test_settings_without_http):
        """Test run without initialization raises error."""
        app = VoiceCaptureApp(test_settings_without_http)

        with pytest.raises(RuntimeError, match="not initialized"):
            await app.run()


class TestVoiceCaptureAppShutdown:
    """Tests for VoiceCaptureApp.shutdown() method."""

    @pytest.mark.asyncio
    async def test_shutdown_without_http(self, test_settings_without_http):
        """Test shutdown without HTTP server."""
        app = VoiceCaptureApp(test_settings_without_http)

        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion.return_value = AsyncMock()

            await app.initialize()
            await app.shutdown()

            # Verify cleanup
            assert app._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_shutdown_with_http(self, test_settings_with_http):
        """Test shutdown stops HTTP server."""
        app = VoiceCaptureApp(test_settings_with_http)

        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion.return_value = AsyncMock()

            await app.initialize()

            # Start HTTP server
            await app._http_server.start()
            assert app._http_server.is_running

            await app.shutdown()

            # HTTP server should be stopped
            assert not app._http_server.is_running

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self, test_settings_without_http):
        """Test shutdown can be called multiple times safely."""
        app = VoiceCaptureApp(test_settings_without_http)

        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion.return_value = AsyncMock()

            await app.initialize()

            # Shutdown multiple times
            await app.shutdown()
            await app.shutdown()  # Should not raise


class TestVoiceCaptureAppHttpIntegration:
    """Integration tests for HTTP server with main application."""

    @pytest.mark.asyncio
    async def test_http_server_receives_orchestrator(self, test_settings_with_http):
        """Test HTTP server is configured with correct orchestrator."""
        app = VoiceCaptureApp(test_settings_with_http)

        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion.return_value = AsyncMock()

            await app.initialize()

            # HTTP server should have the orchestrator
            assert app._http_server.orchestrator is app._orchestrator
            assert app._http_server.db is app._db

            await app.shutdown()

    @pytest.mark.asyncio
    async def test_http_server_receives_file_validator(self, test_settings_with_http):
        """Test HTTP server receives file validator from watcher."""
        app = VoiceCaptureApp(test_settings_with_http)

        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion.return_value = AsyncMock()

            await app.initialize()

            # HTTP server should have the file validator from watcher
            assert app._http_server.file_validator is app._watcher._validator

            await app.shutdown()

    @pytest.mark.asyncio
    async def test_http_server_receives_paths(self, test_settings_with_http):
        """Test HTTP server receives path settings."""
        app = VoiceCaptureApp(test_settings_with_http)

        with patch("src.main.create_whisper_service") as mock_whisper, \
             patch("src.main.NotionService") as mock_notion:
            mock_whisper.return_value = MagicMock(backend_name="whisper_api")
            mock_notion.return_value = AsyncMock()

            await app.initialize()

            # HTTP server should have path settings
            assert app._http_server.paths is app.settings.paths

            await app.shutdown()


# ============================================================================
# Logging Setup Tests
# ============================================================================


class TestLoggingSetup:
    """Tests for logging setup."""

    def test_setup_logging(self, test_settings_without_http):
        """Test logging setup configures handlers."""
        import logging

        # Clear existing handlers
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers = []

        try:
            setup_logging(test_settings_without_http)

            # Should have console handler at minimum
            assert len(root_logger.handlers) >= 1
        finally:
            # Restore original handlers
            root_logger.handlers = original_handlers
