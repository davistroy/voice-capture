"""Tests for CLI commands.

Tests the retry, reset_capture, and queue_status CLI commands.
"""

import asyncio
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from src.config.settings import Settings, reload_settings
from src.db.database import Database
from src.db.models import CaptureRow


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def cli_runner():
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
async def test_db(temp_dir: Path):
    """Create a test database with some sample data."""
    db_path = temp_dir / "test.db"
    db = Database(db_path)
    await db.initialize()

    # Insert some test captures
    # Pending capture
    await db.insert_capture(
        filename="pending_capture.m4a",
        original_path=str(temp_dir / "inbox" / "pending_capture.m4a"),
        device="watch",
        captured_at=datetime(2026, 1, 20, 10, 0, 0),
    )

    # Failed capture
    failed_id = await db.insert_capture(
        filename="failed_capture.m4a",
        original_path=str(temp_dir / "failed" / "failed_capture.m4a"),
        device="phone",
        captured_at=datetime(2026, 1, 20, 11, 0, 0),
    )
    await db.update_status(failed_id, "failed", error="Transcription timeout")
    await db.increment_retry(failed_id)
    await db.increment_retry(failed_id)

    # Another failed capture
    failed_id2 = await db.insert_capture(
        filename="failed_capture2.m4a",
        original_path=str(temp_dir / "failed" / "failed_capture2.m4a"),
        device="watch",
        captured_at=datetime(2026, 1, 20, 12, 0, 0),
    )
    await db.update_status(failed_id2, "failed", error="Notion API error")
    await db.increment_retry(failed_id2)

    # Complete capture
    complete_id = await db.insert_capture(
        filename="complete_capture.m4a",
        original_path=str(temp_dir / "processing" / "complete_capture.m4a"),
        device="watch",
        captured_at=datetime(2026, 1, 20, 9, 0, 0),
    )
    await db.update_status(complete_id, "complete")

    # Transcribing capture (in progress)
    transcribing_id = await db.insert_capture(
        filename="transcribing_capture.m4a",
        original_path=str(temp_dir / "processing" / "transcribing_capture.m4a"),
        device="phone",
        captured_at=datetime(2026, 1, 20, 13, 0, 0),
    )
    await db.update_status(transcribing_id, "transcribing")

    yield db

    await db.close()


@pytest.fixture
def mock_settings(temp_dir: Path):
    """Create mock settings for testing."""
    # Set environment variables
    os.environ["OPENAI_API_KEY"] = "test-openai-key"
    os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
    os.environ["NOTION_API_KEY"] = "test-notion-key"
    os.environ["NOTION_VOICE_CAPTURES_DB_ID"] = "test-db-id"
    os.environ["VOICE_CAPTURE_INBOX_PATH"] = str(temp_dir / "inbox")
    os.environ["VOICE_CAPTURE_PROCESSING_PATH"] = str(temp_dir / "processing")
    os.environ["VOICE_CAPTURE_FAILED_PATH"] = str(temp_dir / "failed")
    os.environ["VOICE_CAPTURE_DB_PATH"] = str(temp_dir / "test.db")
    os.environ["VOICE_CAPTURE_LOG_PATH"] = str(temp_dir / "logs")

    settings = reload_settings()
    settings.ensure_directories_exist()

    yield settings

    # Clean up
    for key in [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NOTION_API_KEY",
        "NOTION_VOICE_CAPTURES_DB_ID", "VOICE_CAPTURE_INBOX_PATH",
        "VOICE_CAPTURE_PROCESSING_PATH", "VOICE_CAPTURE_FAILED_PATH",
        "VOICE_CAPTURE_DB_PATH", "VOICE_CAPTURE_LOG_PATH",
    ]:
        os.environ.pop(key, None)

    reload_settings()


# ============================================================================
# Queue Status Tests
# ============================================================================


class TestQueueStatus:
    """Tests for queue_status CLI command."""

    @pytest.mark.asyncio
    async def test_get_queue_status(self, test_db: Database):
        """Test getting queue status."""
        from src.cli.queue_status import get_queue_status

        status = await get_queue_status(test_db)

        assert status["counts"]["pending"] == 1
        assert status["counts"]["failed"] == 2
        assert status["counts"]["complete"] == 1
        assert status["counts"]["transcribing"] == 1
        assert status["counts"]["total"] == 5

        # Check failed list has details
        assert len(status["failed"]) == 2
        assert any(c.filename == "failed_capture.m4a" for c in status["failed"])

    def test_queue_status_cli_basic(
        self,
        cli_runner: CliRunner,
        mock_settings: Settings,
        test_db: Database,
        temp_dir: Path,
    ):
        """Test basic queue status CLI output."""
        from src.cli.queue_status import queue_status_cli

        # Need to run in a way that uses the test db
        with patch("src.cli.queue_status.get_settings", return_value=mock_settings):
            result = cli_runner.invoke(queue_status_cli)

        # Should succeed
        assert result.exit_code == 0

        # Should show counts
        assert "Pending" in result.output
        assert "Failed" in result.output
        assert "Complete" in result.output

    def test_queue_status_cli_failed_filter(
        self,
        cli_runner: CliRunner,
        mock_settings: Settings,
        temp_dir: Path,
    ):
        """Test queue status with --failed filter."""
        from src.cli.queue_status import queue_status_cli

        with patch("src.cli.queue_status.get_settings", return_value=mock_settings):
            result = cli_runner.invoke(queue_status_cli, ["--failed"])

        assert result.exit_code == 0
        # Should show failed captures section
        assert "Failed Captures" in result.output or "No failed captures" in result.output

    def test_queue_status_cli_verbose(
        self,
        cli_runner: CliRunner,
        mock_settings: Settings,
        temp_dir: Path,
    ):
        """Test queue status with --verbose flag."""
        from src.cli.queue_status import queue_status_cli

        with patch("src.cli.queue_status.get_settings", return_value=mock_settings):
            result = cli_runner.invoke(queue_status_cli, ["--verbose"])

        assert result.exit_code == 0


# ============================================================================
# Reset Capture Tests
# ============================================================================


class TestResetCapture:
    """Tests for reset_capture CLI command."""

    @pytest.mark.asyncio
    async def test_reset_capture_by_id(
        self,
        test_db: Database,
        temp_dir: Path,
    ):
        """Test resetting a capture by ID."""
        from src.cli.reset_capture import reset_capture_by_id

        # Get a failed capture
        failed = await test_db.get_captures_by_status("failed")
        assert len(failed) > 0
        capture_id = failed[0].id

        # Create the file in failed directory
        failed_path = temp_dir / "failed"
        failed_path.mkdir(parents=True, exist_ok=True)
        test_file = failed_path / failed[0].filename
        test_file.write_bytes(b"test audio content")

        # Update capture's current_path to point to the file
        await test_db.update_current_path(capture_id, str(test_file))

        # Reset the capture
        inbox_path = temp_dir / "inbox"
        inbox_path.mkdir(parents=True, exist_ok=True)

        result = await reset_capture_by_id(test_db, capture_id, inbox_path)

        assert result["success"] is True
        assert result["capture_id"] == capture_id
        assert result["file_moved"] is True

        # Verify database state
        capture = await test_db.get_capture_by_id(capture_id)
        assert capture.status == "pending"
        assert capture.retry_count == 0

        # Verify file moved
        assert not test_file.exists()
        assert (inbox_path / failed[0].filename).exists()

    @pytest.mark.asyncio
    async def test_reset_capture_by_filename(
        self,
        test_db: Database,
        temp_dir: Path,
    ):
        """Test resetting a capture by filename."""
        from src.cli.reset_capture import reset_capture_by_filename

        filename = "failed_capture.m4a"
        inbox_path = temp_dir / "inbox"
        inbox_path.mkdir(parents=True, exist_ok=True)

        result = await reset_capture_by_filename(test_db, filename, inbox_path)

        assert result["success"] is True
        assert result["filename"] == filename

    @pytest.mark.asyncio
    async def test_reset_capture_not_found(
        self,
        test_db: Database,
        temp_dir: Path,
    ):
        """Test resetting a non-existent capture."""
        from src.cli.reset_capture import reset_capture_by_id

        inbox_path = temp_dir / "inbox"
        result = await reset_capture_by_id(test_db, 99999, inbox_path)

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_reset_capture_cli_missing_args(self, cli_runner: CliRunner):
        """Test reset_capture CLI without required arguments."""
        from src.cli.reset_capture import reset_capture_cli

        result = cli_runner.invoke(reset_capture_cli)

        assert result.exit_code == 1
        assert "Must specify" in result.output

    def test_reset_capture_cli_conflicting_args(self, cli_runner: CliRunner):
        """Test reset_capture CLI with conflicting arguments."""
        from src.cli.reset_capture import reset_capture_cli

        result = cli_runner.invoke(
            reset_capture_cli,
            ["--filename", "test.m4a", "--capture-id", "1"],
        )

        assert result.exit_code == 1
        assert "Cannot specify both" in result.output


# ============================================================================
# Retry Tests
# ============================================================================


class TestRetry:
    """Tests for retry CLI command."""

    @pytest.mark.asyncio
    async def test_get_failed_captures(self, test_db: Database):
        """Test getting list of failed captures."""
        from src.cli.retry import get_failed_captures

        failed = await get_failed_captures(test_db)

        assert len(failed) == 2
        filenames = [c.filename for c in failed]
        assert "failed_capture.m4a" in filenames
        assert "failed_capture2.m4a" in filenames

    def test_retry_cli_missing_args(self, cli_runner: CliRunner):
        """Test retry CLI without required arguments."""
        from src.cli.retry import retry_cli

        result = cli_runner.invoke(retry_cli)

        assert result.exit_code == 1
        assert "Must specify" in result.output

    def test_retry_cli_conflicting_args(self, cli_runner: CliRunner):
        """Test retry CLI with conflicting arguments."""
        from src.cli.retry import retry_cli

        result = cli_runner.invoke(
            retry_cli,
            ["--capture-id", "1", "--all-failed"],
        )

        assert result.exit_code == 1
        assert "Cannot specify both" in result.output

    def test_retry_cli_list_mode(
        self,
        cli_runner: CliRunner,
        mock_settings: Settings,
        temp_dir: Path,
    ):
        """Test retry CLI in list mode."""
        from src.cli.retry import retry_cli

        with patch("src.cli.retry.get_settings", return_value=mock_settings):
            result = cli_runner.invoke(retry_cli, ["--list"])

        assert result.exit_code == 0

    def test_retry_cli_capture_not_found(
        self,
        cli_runner: CliRunner,
        mock_settings: Settings,
        temp_dir: Path,
    ):
        """Test retry CLI with non-existent capture."""
        from src.cli.retry import retry_cli

        with patch("src.cli.retry.get_settings", return_value=mock_settings):
            result = cli_runner.invoke(retry_cli, ["--capture-id", "99999", "--yes"])

        assert result.exit_code == 1
        assert "not found" in result.output

    @pytest.mark.asyncio
    async def test_retry_single_capture_mocked(
        self,
        test_db: Database,
        temp_dir: Path,
    ):
        """Test retrying a single capture with mocked services."""
        from src.cli.retry import retry_capture

        # Get a failed capture
        failed = await test_db.get_captures_by_status("failed")
        capture_id = failed[0].id

        # Mock the pipeline orchestrator and services
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.notion_page_id = "test-page-id"
        mock_result.notion_page_url = "https://notion.so/test"
        mock_result.error = None
        mock_result.stage = None

        mock_orchestrator = AsyncMock()
        mock_orchestrator.retry_failed.return_value = mock_result

        with patch("src.pipeline.orchestrator.PipelineOrchestrator", return_value=mock_orchestrator), \
             patch("src.transcription.service.TranscriptionService"), \
             patch("src.transcription.whisper_api.WhisperAPIBackend"), \
             patch("src.notion.client.NotionService"), \
             patch("src.classification.ClassificationService"), \
             patch("src.classification.TemplateLoader"):

            # Configure mock settings
            mock_settings_obj = MagicMock()
            mock_settings_obj.openai_api_key = "test-key"
            mock_settings_obj.anthropic_api_key = "test-key"
            mock_settings_obj.notion_api_key = "test-key"
            mock_settings_obj.notion_voice_captures_db_id = "test-db"
            mock_settings_obj.paths.failed = temp_dir / "failed"
            mock_settings_obj.paths.templates = temp_dir / "templates"
            mock_settings_obj.transcription.model = "whisper-1"
            mock_settings_obj.transcription.timeout_seconds = 120
            mock_settings_obj.classification.model = "claude-sonnet"
            mock_settings_obj.classification.confidence_threshold = 0.7
            mock_settings_obj.classification.max_tokens = 2048

            with patch("src.cli.retry.get_settings", return_value=mock_settings_obj):
                result = await retry_capture(test_db, capture_id)

            # The mock should have been called
            mock_orchestrator.retry_failed.assert_called_once_with(capture_id, from_stage=None)

            assert result["success"] is True
            assert result["notion_page_id"] == "test-page-id"


# ============================================================================
# Integration Tests
# ============================================================================


class TestCLIIntegration:
    """Integration tests for CLI commands working together."""

    @pytest.mark.asyncio
    async def test_queue_status_after_reset(
        self,
        test_db: Database,
        temp_dir: Path,
    ):
        """Test that queue status reflects changes after reset."""
        from src.cli.queue_status import get_queue_status
        from src.cli.reset_capture import reset_capture_by_id

        # Get initial status
        initial_status = await get_queue_status(test_db)
        initial_failed = initial_status["counts"]["failed"]
        initial_pending = initial_status["counts"]["pending"]

        # Reset a failed capture
        failed = await test_db.get_captures_by_status("failed")
        capture_id = failed[0].id
        inbox_path = temp_dir / "inbox"

        await reset_capture_by_id(test_db, capture_id, inbox_path)

        # Get new status
        new_status = await get_queue_status(test_db)

        # Failed should decrease, pending should increase
        assert new_status["counts"]["failed"] == initial_failed - 1
        assert new_status["counts"]["pending"] == initial_pending + 1

    def test_cli_help_messages(self, cli_runner: CliRunner):
        """Test that all CLI commands have helpful --help output."""
        from src.cli.retry import retry_cli
        from src.cli.reset_capture import reset_capture_cli
        from src.cli.queue_status import queue_status_cli

        # Test retry --help
        result = cli_runner.invoke(retry_cli, ["--help"])
        assert result.exit_code == 0
        assert "Retry failed voice captures" in result.output
        assert "--capture-id" in result.output
        assert "--all-failed" in result.output
        assert "--from-stage" in result.output

        # Test reset_capture --help
        result = cli_runner.invoke(reset_capture_cli, ["--help"])
        assert result.exit_code == 0
        assert "Reset a failed capture" in result.output
        assert "--filename" in result.output
        assert "--capture-id" in result.output

        # Test queue_status --help
        result = cli_runner.invoke(queue_status_cli, ["--help"])
        assert result.exit_code == 0
        assert "Show processing queue status" in result.output
        assert "--verbose" in result.output
        assert "--failed" in result.output


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_reset_capture_file_not_found(
        self,
        test_db: Database,
        temp_dir: Path,
    ):
        """Test resetting a capture when the file doesn't exist."""
        from src.cli.reset_capture import reset_capture_by_id

        failed = await test_db.get_captures_by_status("failed")
        capture_id = failed[0].id
        inbox_path = temp_dir / "inbox"
        inbox_path.mkdir(parents=True, exist_ok=True)

        # Don't create the file - it should still reset the database status

        result = await reset_capture_by_id(test_db, capture_id, inbox_path)

        # Should succeed in resetting database, but note file wasn't found
        assert result["success"] is True
        assert result["file_found"] is False
        assert result["file_moved"] is False

    @pytest.mark.asyncio
    async def test_queue_status_empty_database(self, temp_dir: Path):
        """Test queue status with an empty database."""
        from src.cli.queue_status import get_queue_status

        db_path = temp_dir / "empty.db"
        db = Database(db_path)
        await db.initialize()

        try:
            status = await get_queue_status(db)

            assert status["counts"]["pending"] == 0
            assert status["counts"]["failed"] == 0
            assert status["counts"]["complete"] == 0
            assert status["counts"]["total"] == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_retry_non_failed_capture(
        self,
        test_db: Database,
        temp_dir: Path,
    ):
        """Test that retry works even on non-failed captures (with warning)."""
        from src.cli.retry import retry_capture

        # Get a pending capture (not failed)
        pending = await test_db.get_captures_by_status("pending")
        assert len(pending) > 0
        capture_id = pending[0].id

        # Mock the services
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.notion_page_id = "test-page-id"
        mock_result.notion_page_url = None
        mock_result.error = None
        mock_result.stage = None

        mock_orchestrator = AsyncMock()
        mock_orchestrator.retry_failed.return_value = mock_result

        with patch("src.pipeline.orchestrator.PipelineOrchestrator", return_value=mock_orchestrator), \
             patch("src.transcription.service.TranscriptionService"), \
             patch("src.transcription.whisper_api.WhisperAPIBackend"), \
             patch("src.notion.client.NotionService"):

            mock_settings_obj = MagicMock()
            mock_settings_obj.openai_api_key = "test-key"
            mock_settings_obj.anthropic_api_key = "test-key"
            mock_settings_obj.notion_api_key = "test-key"
            mock_settings_obj.notion_voice_captures_db_id = "test-db"
            mock_settings_obj.paths.failed = temp_dir / "failed"
            mock_settings_obj.paths.templates = temp_dir / "templates"
            mock_settings_obj.transcription.model = "whisper-1"
            mock_settings_obj.transcription.timeout_seconds = 120
            mock_settings_obj.classification.model = "claude-sonnet"
            mock_settings_obj.classification.confidence_threshold = 0.7
            mock_settings_obj.classification.max_tokens = 2048

            with patch("src.cli.retry.get_settings", return_value=mock_settings_obj):
                # Should work - the CLI shows a warning but doesn't block
                result = await retry_capture(test_db, capture_id)
                assert "success" in result
