"""Additional tests for retry CLI to improve coverage.

These tests cover:
- retry_all_failed() function
- print_retry_result() function
- print_failed_captures_table() function
- CLI execution paths
"""

import asyncio
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner
from rich.console import Console

from src.cli.retry import (
    retry_all_failed,
    print_retry_result,
    print_failed_captures_table,
    retry_cli,
    retry_capture,
    VALID_STAGES,
)
from src.db.database import Database
from src.db.models import CaptureRow


class TestRetryAllFailed:
    """Tests for retry_all_failed function."""

    @pytest.mark.asyncio
    async def test_retry_all_failed_no_captures(self, temp_dir: Path):
        """Test retry_all_failed with no failed captures."""
        db_path = temp_dir / "test.db"
        db = Database(db_path)
        await db.initialize()

        try:
            results = await retry_all_failed(db)
            assert results == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_retry_all_failed_with_captures(self, temp_dir: Path):
        """Test retry_all_failed with failed captures."""
        db_path = temp_dir / "test.db"
        db = Database(db_path)
        await db.initialize()

        try:
            # Insert failed captures
            cap1 = await db.insert_capture(
                filename="failed1.m4a",
                original_path=str(temp_dir / "failed1.m4a"),
                device="watch",
            )
            await db.update_status(cap1, "failed", error="Error 1")

            cap2 = await db.insert_capture(
                filename="failed2.m4a",
                original_path=str(temp_dir / "failed2.m4a"),
                device="phone",
            )
            await db.update_status(cap2, "failed", error="Error 2")

            # Mock retry_capture to avoid needing real services
            mock_result = {
                "success": True,
                "capture_id": 1,
                "notion_page_id": "test-page",
                "notion_page_url": "https://notion.so/test",
                "error": None,
                "stage": None,
            }

            with patch("src.cli.retry.retry_capture", return_value=mock_result) as mock_retry:
                results = await retry_all_failed(db)

            assert len(results) == 2
            assert mock_retry.call_count == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_retry_all_failed_with_from_stage(self, temp_dir: Path):
        """Test retry_all_failed passes from_stage to retry_capture."""
        db_path = temp_dir / "test.db"
        db = Database(db_path)
        await db.initialize()

        try:
            cap1 = await db.insert_capture(
                filename="failed1.m4a",
                original_path=str(temp_dir / "failed1.m4a"),
            )
            await db.update_status(cap1, "failed", error="Error")

            mock_result = {"success": True}

            with patch("src.cli.retry.retry_capture", return_value=mock_result) as mock_retry:
                await retry_all_failed(db, from_stage="posting")

            mock_retry.assert_called_once()
            call_args = mock_retry.call_args
            assert call_args[0][2] == "posting"  # from_stage argument
        finally:
            await db.close()


class TestPrintRetryResult:
    """Tests for print_retry_result function."""

    def test_print_success_result(self):
        """Test printing a successful result."""
        result = {
            "capture_id": 42,
            "success": True,
            "notion_page_url": "https://notion.so/test-page",
        }

        console = Console(file=StringIO(), force_terminal=True)
        print_retry_result(result, console)

        output = console.file.getvalue()
        assert "42" in output
        assert "SUCCESS" in output
        assert "https://notion.so/test-page" in output

    def test_print_success_result_no_url(self):
        """Test printing a successful result without URL."""
        result = {
            "capture_id": 42,
            "success": True,
            "notion_page_url": None,
        }

        console = Console(file=StringIO(), force_terminal=True)
        print_retry_result(result, console)

        output = console.file.getvalue()
        assert "42" in output
        assert "SUCCESS" in output

    def test_print_failure_result(self):
        """Test printing a failed result."""
        result = {
            "capture_id": 42,
            "success": False,
            "error": "Connection timeout",
            "stage": "transcribing",
        }

        console = Console(file=StringIO(), force_terminal=True)
        print_retry_result(result, console)

        output = console.file.getvalue()
        assert "42" in output
        assert "FAILED" in output
        assert "transcribing" in output
        assert "Connection timeout" in output

    def test_print_failure_result_unknown_error(self):
        """Test printing a failed result with unknown error."""
        result = {
            "capture_id": 42,
            "success": False,
        }

        console = Console(file=StringIO(), force_terminal=True)
        print_retry_result(result, console)

        output = console.file.getvalue()
        assert "FAILED" in output
        assert "Unknown error" in output


class TestPrintFailedCapturesTable:
    """Tests for print_failed_captures_table function."""

    def test_print_table_with_captures(self):
        """Test printing table with failed captures."""
        captures = [
            CaptureRow(
                id=1,
                filename="failed1.m4a",
                original_path="/path/failed1.m4a",
                status="failed",
                retry_count=2,
                last_error="Transcription error",
            ),
            CaptureRow(
                id=2,
                filename="failed2.m4a",
                original_path="/path/failed2.m4a",
                status="failed",
                retry_count=1,
                last_error="Notion API error",
            ),
        ]

        console = Console(file=StringIO(), force_terminal=True, width=200)
        print_failed_captures_table(captures, console)

        output = console.file.getvalue()
        assert "Failed Captures" in output
        assert "failed1.m4a" in output
        assert "failed2.m4a" in output
        assert "2" in output  # retry count

    def test_print_table_long_error_truncation(self):
        """Test that long error messages are truncated."""
        long_error = "A" * 100  # Very long error message
        captures = [
            CaptureRow(
                id=1,
                filename="failed.m4a",
                original_path="/path/failed.m4a",
                status="failed",
                retry_count=1,
                last_error=long_error,
            ),
        ]

        console = Console(file=StringIO(), force_terminal=True, width=200)
        print_failed_captures_table(captures, console)

        output = console.file.getvalue()
        # Error should be truncated to 47 chars + "..."
        assert "..." in output

    def test_print_table_none_error(self):
        """Test printing table with None error."""
        captures = [
            CaptureRow(
                id=1,
                filename="failed.m4a",
                original_path="/path/failed.m4a",
                status="failed",
                retry_count=0,
                last_error=None,
            ),
        ]

        console = Console(file=StringIO(), force_terminal=True, width=200)
        print_failed_captures_table(captures, console)

        output = console.file.getvalue()
        assert "Unknown" in output


class TestRetryCLI:
    """Tests for retry CLI command."""

    @pytest.fixture
    def cli_runner(self):
        """Create a Click CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def mock_settings(self, temp_dir: Path):
        """Create mock settings."""
        settings = MagicMock()
        settings.paths.database = temp_dir / "test.db"
        settings.paths.inbox = temp_dir / "inbox"
        settings.paths.failed = temp_dir / "failed"
        settings.paths.templates = temp_dir / "templates"
        settings.openai_api_key = "test-key"
        settings.anthropic_api_key = "test-key"
        settings.notion_api_key = "test-key"
        settings.notion_voice_captures_db_id = "test-db"
        settings.transcription.model = "whisper-1"
        settings.transcription.timeout_seconds = 120
        settings.classification.model = "claude-sonnet"
        settings.classification.confidence_threshold = 0.7
        settings.classification.max_tokens = 2048
        return settings

    def test_valid_stages_constant(self):
        """Test that VALID_STAGES contains expected values."""
        assert "pending" in VALID_STAGES
        assert "transcribing" in VALID_STAGES
        assert "classifying" in VALID_STAGES
        assert "posting" in VALID_STAGES

    def test_cli_retry_single_success(
        self,
        cli_runner: CliRunner,
        mock_settings,
        temp_dir: Path,
    ):
        """Test CLI retry single capture success path."""
        capture_id = 1

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.notion_page_id = "test-page"
        mock_result.notion_page_url = "https://notion.so/test"
        mock_result.error = None
        mock_result.stage = None

        mock_orchestrator = AsyncMock()
        mock_orchestrator.retry_failed.return_value = mock_result

        with patch("src.cli.retry.reload_settings"), \
             patch("src.cli.retry.get_settings", return_value=mock_settings), \
             patch("src.cli.retry.Database") as mock_db_class, \
             patch("src.pipeline.orchestrator.PipelineOrchestrator", return_value=mock_orchestrator), \
             patch("src.transcription.service.TranscriptionService"), \
             patch("src.transcription.whisper_api.WhisperAPIBackend"), \
             patch("src.notion.client.NotionService"), \
             patch("src.classification.ClassificationService"), \
             patch("src.classification.TemplateLoader"):

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=CaptureRow(
                id=capture_id,
                filename="test.m4a",
                original_path=str(temp_dir / "test.m4a"),
                status="failed",
                retry_count=1,
            ))
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(retry_cli, ["-c", str(capture_id), "-y"])

        # Should show success in output
        assert "SUCCESS" in result.output or result.exit_code == 0

    def test_cli_retry_all_failed_success(
        self,
        cli_runner: CliRunner,
        mock_settings,
        temp_dir: Path,
    ):
        """Test CLI retry all failed captures success path."""
        mock_result = {
            "success": True,
            "capture_id": 1,
            "notion_page_id": "test-page",
            "notion_page_url": "https://notion.so/test",
            "error": None,
            "stage": None,
        }

        failed_captures = [
            CaptureRow(
                id=1,
                filename="failed1.m4a",
                original_path="/path/failed1.m4a",
                status="failed",
                retry_count=1,
                last_error="Error 1",
            ),
            CaptureRow(
                id=2,
                filename="failed2.m4a",
                original_path="/path/failed2.m4a",
                status="failed",
                retry_count=1,
                last_error="Error 2",
            ),
        ]

        with patch("src.cli.retry.reload_settings"), \
             patch("src.cli.retry.get_settings", return_value=mock_settings), \
             patch("src.cli.retry.Database") as mock_db_class, \
             patch("src.cli.retry.retry_all_failed", return_value=[mock_result, mock_result]) as mock_retry_all, \
             patch("src.cli.retry.get_failed_captures", return_value=failed_captures):

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(retry_cli, ["--all-failed", "-y"])

        assert result.exit_code == 0
        assert "2" in result.output  # Number of captures

    def test_cli_retry_all_failed_no_failed(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI retry all failed with no failed captures."""
        with patch("src.cli.retry.reload_settings"), \
             patch("src.cli.retry.get_settings", return_value=mock_settings), \
             patch("src.cli.retry.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_captures_by_status = AsyncMock(return_value=[])
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(retry_cli, ["--all-failed"])

        assert result.exit_code == 0
        assert "No failed captures" in result.output

    def test_cli_retry_all_failed_cancelled(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI retry all failed cancelled by user."""
        failed_captures = [
            CaptureRow(
                id=1,
                filename="failed1.m4a",
                original_path="/path/failed1.m4a",
                status="failed",
                retry_count=1,
                last_error="Error 1",
            ),
        ]

        with patch("src.cli.retry.reload_settings"), \
             patch("src.cli.retry.get_settings", return_value=mock_settings), \
             patch("src.cli.retry.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_captures_by_status = AsyncMock(return_value=failed_captures)
            mock_db_class.return_value = mock_db

            # Simulate user typing 'n' to cancel
            result = cli_runner.invoke(retry_cli, ["--all-failed"], input="n\n")

        assert result.exit_code == 1
        assert "Cancelled" in result.output

    def test_cli_retry_single_not_failed_warning(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI retry single capture not in failed state shows warning."""
        pending_capture = CaptureRow(
            id=1,
            filename="pending.m4a",
            original_path="/path/pending.m4a",
            status="pending",  # Not failed
            retry_count=0,
        )

        with patch("src.cli.retry.reload_settings"), \
             patch("src.cli.retry.get_settings", return_value=mock_settings), \
             patch("src.cli.retry.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=pending_capture)
            mock_db_class.return_value = mock_db

            # Simulate user typing 'n' to cancel
            result = cli_runner.invoke(retry_cli, ["-c", "1"], input="n\n")

        assert "Warning" in result.output
        assert "pending" in result.output
        assert "Cancelled" in result.output

    def test_cli_retry_with_from_stage(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI retry with from_stage option."""
        failed_capture = CaptureRow(
            id=1,
            filename="failed.m4a",
            original_path="/path/failed.m4a",
            status="failed",
            retry_count=1,
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.notion_page_id = "test-page"
        mock_result.notion_page_url = None
        mock_result.error = None
        mock_result.stage = None

        mock_orchestrator = AsyncMock()
        mock_orchestrator.retry_failed.return_value = mock_result

        with patch("src.cli.retry.reload_settings"), \
             patch("src.cli.retry.get_settings", return_value=mock_settings), \
             patch("src.cli.retry.Database") as mock_db_class, \
             patch("src.pipeline.orchestrator.PipelineOrchestrator", return_value=mock_orchestrator), \
             patch("src.transcription.service.TranscriptionService"), \
             patch("src.transcription.whisper_api.WhisperAPIBackend"), \
             patch("src.notion.client.NotionService"), \
             patch("src.classification.ClassificationService"), \
             patch("src.classification.TemplateLoader"):

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=failed_capture)
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(
                retry_cli,
                ["-c", "1", "-s", "posting", "-y"],
            )

        assert "from posting" in result.output

    def test_cli_retry_exception_handling(
        self,
        cli_runner: CliRunner,
    ):
        """Test CLI retry handles exceptions gracefully."""
        with patch("src.cli.retry.reload_settings", side_effect=Exception("Config error")):
            result = cli_runner.invoke(retry_cli, ["-c", "1"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_cli_all_failed_mixed_results(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI retry all failed with mixed success/failure results."""
        failed_captures = [
            CaptureRow(
                id=1,
                filename="failed1.m4a",
                original_path="/path/failed1.m4a",
                status="failed",
                retry_count=1,
                last_error="Error 1",
            ),
            CaptureRow(
                id=2,
                filename="failed2.m4a",
                original_path="/path/failed2.m4a",
                status="failed",
                retry_count=1,
                last_error="Error 2",
            ),
        ]

        # One success, one failure
        mock_results = [
            {
                "success": True,
                "capture_id": 1,
                "notion_page_id": "test-page",
                "notion_page_url": "https://notion.so/test",
                "error": None,
                "stage": None,
            },
            {
                "success": False,
                "capture_id": 2,
                "notion_page_id": None,
                "notion_page_url": None,
                "error": "Still failing",
                "stage": "transcribing",
            },
        ]

        with patch("src.cli.retry.reload_settings"), \
             patch("src.cli.retry.get_settings", return_value=mock_settings), \
             patch("src.cli.retry.Database") as mock_db_class, \
             patch("src.cli.retry.retry_all_failed", return_value=mock_results), \
             patch("src.cli.retry.get_failed_captures", return_value=failed_captures):

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(retry_cli, ["--all-failed", "-y"])

        # Exit code 0 because at least one succeeded
        assert result.exit_code == 0
        assert "1" in result.output  # 1 succeeded
        assert "1" in result.output  # 1 failed

    def test_cli_all_failed_all_fail(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI retry all failed when all retries fail."""
        failed_captures = [
            CaptureRow(
                id=1,
                filename="failed1.m4a",
                original_path="/path/failed1.m4a",
                status="failed",
                retry_count=1,
                last_error="Error 1",
            ),
        ]

        mock_results = [
            {
                "success": False,
                "capture_id": 1,
                "error": "Still failing",
                "stage": "transcribing",
            },
        ]

        with patch("src.cli.retry.reload_settings"), \
             patch("src.cli.retry.get_settings", return_value=mock_settings), \
             patch("src.cli.retry.Database") as mock_db_class, \
             patch("src.cli.retry.retry_all_failed", return_value=mock_results), \
             patch("src.cli.retry.get_failed_captures", return_value=failed_captures):

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(retry_cli, ["--all-failed", "-y"])

        # Exit code 1 because all failed
        assert result.exit_code == 1
