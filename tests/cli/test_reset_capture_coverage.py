"""Additional tests for reset_capture CLI to improve coverage.

These tests cover:
- Full CLI execution paths
- Error handling scenarios
- File move operations
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from src.cli.reset_capture import (
    reset_capture_cli,
    reset_capture_by_id,
    reset_capture_by_filename,
    _do_reset,
)
from src.db.database import Database
from src.db.models import CaptureRow


class TestResetCaptureCLI:
    """Tests for reset_capture CLI command."""

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
        return settings

    def test_cli_reset_by_id_success(
        self,
        cli_runner: CliRunner,
        mock_settings,
        temp_dir: Path,
    ):
        """Test CLI reset by ID success path."""
        # Create failed directory and file
        failed_dir = temp_dir / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        test_file = failed_dir / "test.m4a"
        test_file.write_bytes(b"audio content")

        inbox_dir = temp_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)

        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(failed_dir / "test.m4a"),
            current_path=str(test_file),
            status="failed",
            retry_count=2,
            last_error="Test error that is reasonably short",
        )

        with patch("src.cli.reset_capture.reload_settings"), \
             patch("src.cli.reset_capture.get_settings", return_value=mock_settings), \
             patch("src.cli.reset_capture.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=capture)
            mock_db.update_current_path = AsyncMock(return_value=True)
            mock_db.reset_capture = AsyncMock(return_value=True)
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(reset_capture_cli, ["-c", "1", "-y"])

        assert result.exit_code == 0
        assert "successful" in result.output.lower() or "Reset" in result.output

    def test_cli_reset_by_filename_success(
        self,
        cli_runner: CliRunner,
        mock_settings,
        temp_dir: Path,
    ):
        """Test CLI reset by filename success path."""
        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(temp_dir / "failed" / "test.m4a"),
            current_path=None,
            status="failed",
            retry_count=1,
        )

        with patch("src.cli.reset_capture.reload_settings"), \
             patch("src.cli.reset_capture.get_settings", return_value=mock_settings), \
             patch("src.cli.reset_capture.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_filename = AsyncMock(return_value=capture)
            mock_db.reset_capture = AsyncMock(return_value=True)
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(
                reset_capture_cli,
                ["-f", "test.m4a", "-y"],
            )

        assert "successful" in result.output.lower() or result.exit_code == 0

    def test_cli_reset_capture_not_found_by_id(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI reset when capture not found by ID."""
        with patch("src.cli.reset_capture.reload_settings"), \
             patch("src.cli.reset_capture.get_settings", return_value=mock_settings), \
             patch("src.cli.reset_capture.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=None)
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(reset_capture_cli, ["-c", "999", "-y"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_cli_reset_capture_not_found_by_filename(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI reset when capture not found by filename."""
        with patch("src.cli.reset_capture.reload_settings"), \
             patch("src.cli.reset_capture.get_settings", return_value=mock_settings), \
             patch("src.cli.reset_capture.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_filename = AsyncMock(return_value=None)
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(
                reset_capture_cli,
                ["-f", "nonexistent.m4a", "-y"],
            )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_cli_reset_non_failed_warning(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI reset shows warning for non-failed capture."""
        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path="/path/test.m4a",
            status="pending",  # Not failed
            retry_count=0,
        )

        with patch("src.cli.reset_capture.reload_settings"), \
             patch("src.cli.reset_capture.get_settings", return_value=mock_settings), \
             patch("src.cli.reset_capture.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=capture)
            mock_db.reset_capture = AsyncMock(return_value=True)
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(reset_capture_cli, ["-c", "1", "-y"])

        assert "Warning" in result.output
        assert "pending" in result.output

    def test_cli_reset_cancelled(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test CLI reset cancelled by user."""
        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path="/path/test.m4a",
            status="failed",
            retry_count=1,
        )

        with patch("src.cli.reset_capture.reload_settings"), \
             patch("src.cli.reset_capture.get_settings", return_value=mock_settings), \
             patch("src.cli.reset_capture.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=capture)
            mock_db_class.return_value = mock_db

            # Simulate user typing 'n' to cancel
            result = cli_runner.invoke(reset_capture_cli, ["-c", "1"], input="n\n")

        assert result.exit_code == 1
        assert "Cancelled" in result.output

    def test_cli_reset_exception_handling(
        self,
        cli_runner: CliRunner,
    ):
        """Test CLI reset handles exceptions gracefully."""
        with patch("src.cli.reset_capture.reload_settings", side_effect=Exception("Config error")):
            result = cli_runner.invoke(reset_capture_cli, ["-c", "1"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_cli_reset_long_error_truncation(
        self,
        cli_runner: CliRunner,
        mock_settings,
    ):
        """Test that long error messages are truncated in display."""
        long_error = "A" * 100  # Very long error message

        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path="/path/test.m4a",
            status="failed",
            retry_count=1,
            last_error=long_error,
        )

        with patch("src.cli.reset_capture.reload_settings"), \
             patch("src.cli.reset_capture.get_settings", return_value=mock_settings), \
             patch("src.cli.reset_capture.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=capture)
            mock_db.reset_capture = AsyncMock(return_value=True)
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(reset_capture_cli, ["-c", "1", "-y"])

        # Error should be truncated with "..."
        assert "..." in result.output

    def test_cli_reset_file_not_found_note(
        self,
        cli_runner: CliRunner,
        mock_settings,
        temp_dir: Path,
    ):
        """Test that note is shown when file is not found."""
        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(temp_dir / "nonexistent" / "test.m4a"),
            current_path=str(temp_dir / "nonexistent" / "test.m4a"),
            status="failed",
            retry_count=1,
        )

        with patch("src.cli.reset_capture.reload_settings"), \
             patch("src.cli.reset_capture.get_settings", return_value=mock_settings), \
             patch("src.cli.reset_capture.Database") as mock_db_class:

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=capture)
            mock_db.reset_capture = AsyncMock(return_value=True)
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(reset_capture_cli, ["-c", "1", "-y"])

        # Should show note about file not found
        assert "Note" in result.output or "manually" in result.output.lower()

    def test_cli_reset_failure(
        self,
        cli_runner: CliRunner,
        mock_settings,
        temp_dir: Path,
    ):
        """Test CLI reset when reset operation fails."""
        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(temp_dir / "test.m4a"),
            current_path=None,
            status="failed",
            retry_count=1,
        )

        with patch("src.cli.reset_capture.reload_settings"), \
             patch("src.cli.reset_capture.get_settings", return_value=mock_settings), \
             patch("src.cli.reset_capture.Database") as mock_db_class, \
             patch(
                 "src.cli.reset_capture.reset_capture_by_id",
                 return_value={"success": False, "error": "Database error"},
             ):

            mock_db = AsyncMock()
            mock_db.initialize = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db.get_capture_by_id = AsyncMock(return_value=capture)
            mock_db_class.return_value = mock_db

            result = cli_runner.invoke(reset_capture_cli, ["-c", "1", "-y"])

        assert result.exit_code == 1
        assert "failed" in result.output.lower() or "error" in result.output.lower()


class TestDoReset:
    """Tests for _do_reset internal function."""

    @pytest.mark.asyncio
    async def test_do_reset_file_move_error(self, temp_dir: Path):
        """Test _do_reset when file move fails."""
        db = MagicMock()
        db.update_current_path = AsyncMock()
        db.reset_capture = AsyncMock(return_value=True)

        # Create a file in a directory
        source_dir = temp_dir / "source"
        source_dir.mkdir()
        source_file = source_dir / "test.m4a"
        source_file.write_bytes(b"content")

        inbox_path = temp_dir / "inbox"
        inbox_path.mkdir(parents=True, exist_ok=True)

        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(source_file),
            current_path=str(source_file),
            status="failed",
        )

        # Mock shutil.move to raise an exception
        with patch("src.cli.reset_capture.shutil.move", side_effect=PermissionError("Cannot move")):
            result = await _do_reset(db, capture, inbox_path)

        assert result["success"] is False
        assert "Failed to move file" in result["error"]

    @pytest.mark.asyncio
    async def test_do_reset_db_reset_fails(self, temp_dir: Path):
        """Test _do_reset when database reset fails."""
        db = MagicMock()
        db.update_current_path = AsyncMock()
        db.reset_capture = AsyncMock(return_value=False)  # Simulate failure

        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(temp_dir / "test.m4a"),
            current_path=None,
            status="failed",
        )

        inbox_path = temp_dir / "inbox"
        inbox_path.mkdir(parents=True, exist_ok=True)

        result = await _do_reset(db, capture, inbox_path)

        assert result["success"] is False
        assert "Failed to reset database" in result["error"]

    @pytest.mark.asyncio
    async def test_do_reset_no_current_path(self, temp_dir: Path):
        """Test _do_reset with no current_path (uses original_path)."""
        db = MagicMock()
        db.update_current_path = AsyncMock()
        db.reset_capture = AsyncMock(return_value=True)

        # Create file at original path
        source_file = temp_dir / "test.m4a"
        source_file.write_bytes(b"content")

        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(source_file),
            current_path=None,  # No current path
            status="failed",
        )

        inbox_path = temp_dir / "inbox"
        inbox_path.mkdir(parents=True, exist_ok=True)

        result = await _do_reset(db, capture, inbox_path)

        assert result["success"] is True
        assert result["file_found"] is True


class TestResetCaptureByFilename:
    """Tests for reset_capture_by_filename function."""

    @pytest.mark.asyncio
    async def test_reset_by_filename_not_found(self, temp_dir: Path):
        """Test reset_capture_by_filename when capture not found."""
        db = MagicMock()
        db.get_capture_by_filename = AsyncMock(return_value=None)

        inbox_path = temp_dir / "inbox"

        result = await reset_capture_by_filename(db, "nonexistent.m4a", inbox_path)

        assert result["success"] is False
        assert "not found" in result["error"]


class TestResetCaptureById:
    """Tests for reset_capture_by_id function."""

    @pytest.mark.asyncio
    async def test_reset_by_id_not_found(self, temp_dir: Path):
        """Test reset_capture_by_id when capture not found."""
        db = MagicMock()
        db.get_capture_by_id = AsyncMock(return_value=None)

        inbox_path = temp_dir / "inbox"

        result = await reset_capture_by_id(db, 999, inbox_path)

        assert result["success"] is False
        assert "not found" in result["error"]
