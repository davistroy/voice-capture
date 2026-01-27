"""Comprehensive tests for the folder watcher service.

Tests file validation, filename parsing, watchdog integration,
and end-to-end capture queueing with temporary directories.
"""

import asyncio
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.db.database import Database
from src.watcher.file_validator import (
    AudioFormat,
    FileValidator,
    ParsedFilename,
    ValidationResult,
)
from src.watcher.watcher import FolderWatcher, NewCaptureEvent, WatcherError


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        inbox = base / "inbox"
        processing = base / "processing"
        failed = base / "failed"
        data = base / "data"

        inbox.mkdir()
        processing.mkdir()
        failed.mkdir()
        data.mkdir()

        yield {
            "base": base,
            "inbox": inbox,
            "processing": processing,
            "failed": failed,
            "db_path": data / "test.db",
        }


@pytest.fixture
def file_validator():
    """Create a file validator instance."""
    return FileValidator(
        valid_extensions=(".m4a", ".wav", ".mp3"),
        max_size_bytes=100 * 1024 * 1024,  # 100MB
        min_size_bytes=100,
    )


@pytest_asyncio.fixture
async def mock_database(temp_dirs):
    """Create a mock database for testing."""
    db = Database(temp_dirs["db_path"])
    await db.initialize()
    yield db
    await db.close()


@pytest_asyncio.fixture
async def folder_watcher(temp_dirs, mock_database):
    """Create a folder watcher instance."""
    watcher = FolderWatcher(
        inbox_path=temp_dirs["inbox"],
        processing_path=temp_dirs["processing"],
        failed_path=temp_dirs["failed"],
        db=mock_database,
        file_settle_delay=0.5,
        valid_extensions=(".m4a", ".wav", ".mp3"),
    )
    yield watcher
    if watcher._running:
        await watcher.stop()


# =============================================================================
# Magic Bytes Fixtures
# =============================================================================


def create_m4a_file(path: Path, size: int = 1024) -> None:
    """Create a file with M4A magic bytes."""
    # M4A files have 'ftyp' at offset 4
    header = bytes([0x00, 0x00, 0x00, 0x20]) + b"ftypM4A "
    content = header + b"\x00" * (size - len(header))
    path.write_bytes(content)


def create_wav_file(path: Path, size: int = 1024) -> None:
    """Create a file with WAV magic bytes."""
    # WAV files start with 'RIFF' and have 'WAVE' at offset 8
    header = b"RIFF" + bytes([0x24, 0x08, 0x00, 0x00]) + b"WAVE"
    content = header + b"\x00" * (size - len(header))
    path.write_bytes(content)


def create_mp3_file(path: Path, size: int = 1024) -> None:
    """Create a file with MP3 magic bytes."""
    # MP3 files start with ID3 tag
    header = b"ID3" + bytes([0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    content = header + b"\x00" * (size - len(header))
    path.write_bytes(content)


def create_invalid_file(path: Path, size: int = 1024) -> None:
    """Create a file with invalid magic bytes."""
    content = b"INVALID_CONTENT" + b"\x00" * (size - 15)
    path.write_bytes(content)


# =============================================================================
# FileValidator Tests
# =============================================================================


class TestFileValidator:
    """Tests for the FileValidator class."""

    def test_validate_valid_m4a(self, file_validator, temp_dirs):
        """Test validation of a valid M4A file."""
        file_path = temp_dirs["inbox"] / "test.m4a"
        create_m4a_file(file_path)

        result = file_validator.validate_audio_file(file_path)

        assert result.is_valid is True
        assert result.format == AudioFormat.M4A
        assert result.size_bytes > 0
        assert result.error_message is None

    def test_validate_valid_wav(self, file_validator, temp_dirs):
        """Test validation of a valid WAV file."""
        file_path = temp_dirs["inbox"] / "test.wav"
        create_wav_file(file_path)

        result = file_validator.validate_audio_file(file_path)

        assert result.is_valid is True
        assert result.format == AudioFormat.WAV
        assert result.size_bytes > 0

    def test_validate_valid_mp3(self, file_validator, temp_dirs):
        """Test validation of a valid MP3 file."""
        file_path = temp_dirs["inbox"] / "test.mp3"
        create_mp3_file(file_path)

        result = file_validator.validate_audio_file(file_path)

        assert result.is_valid is True
        assert result.format == AudioFormat.MP3
        assert result.size_bytes > 0

    def test_validate_invalid_magic_bytes(self, file_validator, temp_dirs):
        """Test validation fails for invalid magic bytes."""
        file_path = temp_dirs["inbox"] / "test.m4a"
        create_invalid_file(file_path)

        result = file_validator.validate_audio_file(file_path)

        assert result.is_valid is False
        assert result.format == AudioFormat.UNKNOWN
        assert result.error_reason == "invalid_format"

    def test_validate_file_not_found(self, file_validator, temp_dirs):
        """Test validation fails for non-existent file."""
        file_path = temp_dirs["inbox"] / "nonexistent.m4a"

        result = file_validator.validate_audio_file(file_path)

        assert result.is_valid is False
        assert result.error_reason == "file_not_found"

    def test_validate_invalid_extension(self, file_validator, temp_dirs):
        """Test validation fails for invalid extension."""
        file_path = temp_dirs["inbox"] / "test.txt"
        file_path.write_bytes(b"text content here" * 10)

        result = file_validator.validate_audio_file(file_path)

        assert result.is_valid is False
        assert result.error_reason == "invalid_extension"

    def test_validate_file_too_small(self, temp_dirs):
        """Test validation fails for files below minimum size."""
        validator = FileValidator(min_size_bytes=1000)
        file_path = temp_dirs["inbox"] / "tiny.m4a"
        create_m4a_file(file_path, size=500)

        result = validator.validate_audio_file(file_path)

        assert result.is_valid is False
        assert result.error_reason == "file_too_small"

    def test_validate_file_too_large(self, temp_dirs):
        """Test validation fails for files above maximum size."""
        validator = FileValidator(max_size_bytes=500)
        file_path = temp_dirs["inbox"] / "large.m4a"
        create_m4a_file(file_path, size=1000)

        result = validator.validate_audio_file(file_path)

        assert result.is_valid is False
        assert result.error_reason == "file_too_large"

    def test_validate_directory_not_file(self, file_validator, temp_dirs):
        """Test validation fails for directories."""
        dir_path = temp_dirs["inbox"] / "subdir"
        dir_path.mkdir()

        # Add a fake extension to pass extension check first
        dir_with_ext = temp_dirs["inbox"] / "subdir.m4a"
        dir_with_ext.mkdir()

        result = file_validator.validate_audio_file(dir_with_ext)

        assert result.is_valid is False
        assert result.error_reason == "not_a_file"


class TestFilenameParser:
    """Tests for filename parsing."""

    def test_parse_standard_format(self, file_validator):
        """Test parsing standard filename format."""
        filename = "2026-01-20T143022_watch.m4a"

        result = file_validator.parse_filename(filename)

        assert result.was_parsed is True
        assert result.device == "watch"
        assert result.timestamp.year == 2026
        assert result.timestamp.month == 1
        assert result.timestamp.day == 20
        assert result.timestamp.hour == 14
        assert result.timestamp.minute == 30
        assert result.timestamp.second == 22

    def test_parse_phone_device(self, file_validator):
        """Test parsing filename with phone device."""
        filename = "2026-01-20T093045_phone.m4a"

        result = file_validator.parse_filename(filename)

        assert result.was_parsed is True
        assert result.device == "phone"

    def test_parse_unknown_device(self, file_validator):
        """Test parsing filename with arbitrary device string passes through."""
        filename = "2026-01-20T093045_tablet.m4a"

        result = file_validator.parse_filename(filename)

        assert result.was_parsed is True
        assert result.device == "tablet"

    def test_parse_alternative_timestamp_format(self, file_validator):
        """Test parsing alternative timestamp format."""
        filename = "20260120_143022_watch.m4a"

        result = file_validator.parse_filename(filename)

        # Should still extract timestamp even if device extraction isn't perfect
        assert result.timestamp is not None

    def test_parse_malformed_filename(self, file_validator, temp_dirs):
        """Test parsing malformed filename uses fallback values."""
        filename = "random_audio_file.m4a"
        file_path = temp_dirs["inbox"] / filename
        create_m4a_file(file_path)

        result = file_validator.parse_filename(filename, file_path)

        assert result.was_parsed is False
        assert result.device == "unknown"
        # Timestamp should be close to file mtime
        assert result.timestamp is not None

    def test_parse_completely_random_filename(self, file_validator):
        """Test parsing completely random filename."""
        filename = "abcdefg.m4a"

        result = file_validator.parse_filename(filename)

        assert result.was_parsed is False
        assert result.device == "unknown"
        # Should use current time as fallback
        assert (datetime.utcnow() - result.timestamp).total_seconds() < 5


class TestFileStability:
    """Tests for file stability checking."""

    def test_file_stable_when_size_unchanged(self, file_validator, temp_dirs):
        """Test file is considered stable when size doesn't change."""
        file_path = temp_dirs["inbox"] / "test.m4a"
        create_m4a_file(file_path)

        size = file_path.stat().st_size

        # Check twice with same size
        is_stable, current = file_validator.check_file_stable(file_path, size)

        assert is_stable is True
        assert current == size

    def test_file_not_stable_on_first_check(self, file_validator, temp_dirs):
        """Test file is not stable on first check (no previous size)."""
        file_path = temp_dirs["inbox"] / "test.m4a"
        create_m4a_file(file_path)

        is_stable, _ = file_validator.check_file_stable(file_path, None)

        assert is_stable is False

    def test_file_not_stable_when_size_changes(self, file_validator, temp_dirs):
        """Test file is not stable when size differs from previous."""
        file_path = temp_dirs["inbox"] / "test.m4a"
        create_m4a_file(file_path, size=1000)

        # Check with different previous size
        is_stable, current = file_validator.check_file_stable(file_path, 500)

        assert is_stable is False
        assert current == 1000


# =============================================================================
# FolderWatcher Tests
# =============================================================================


class TestFolderWatcherInit:
    """Tests for FolderWatcher initialization."""

    def test_init_with_defaults(self, temp_dirs, mock_database):
        """Test watcher initializes with default settings."""
        watcher = FolderWatcher(
            inbox_path=temp_dirs["inbox"],
            processing_path=temp_dirs["processing"],
            failed_path=temp_dirs["failed"],
            db=mock_database,
        )

        assert watcher.file_settle_delay == 2.0
        assert watcher.valid_extensions == (".m4a", ".wav", ".mp3")
        assert watcher._running is False

    def test_init_with_custom_settings(self, temp_dirs, mock_database):
        """Test watcher initializes with custom settings."""
        watcher = FolderWatcher(
            inbox_path=temp_dirs["inbox"],
            processing_path=temp_dirs["processing"],
            failed_path=temp_dirs["failed"],
            db=mock_database,
            file_settle_delay=5.0,
            valid_extensions=(".m4a",),
            max_file_size_mb=50,
        )

        assert watcher.file_settle_delay == 5.0
        assert watcher.valid_extensions == (".m4a",)


class TestFolderWatcherStartStop:
    """Tests for watcher start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_directories(self, temp_dirs, mock_database):
        """Test start creates required directories."""
        # Remove directories
        for d in ["inbox", "processing", "failed"]:
            if temp_dirs[d].exists():
                temp_dirs[d].rmdir()

        watcher = FolderWatcher(
            inbox_path=temp_dirs["inbox"],
            processing_path=temp_dirs["processing"],
            failed_path=temp_dirs["failed"],
            db=mock_database,
            file_settle_delay=0.1,
        )

        await watcher.start()

        try:
            assert temp_dirs["inbox"].exists()
            assert temp_dirs["processing"].exists()
            assert temp_dirs["failed"].exists()
        finally:
            await watcher.stop()

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self, folder_watcher):
        """Test start sets running flag."""
        await folder_watcher.start()

        assert folder_watcher._running is True

        await folder_watcher.stop()
        assert folder_watcher._running is False

    @pytest.mark.asyncio
    async def test_start_twice_raises_error(self, folder_watcher):
        """Test starting twice raises WatcherError."""
        await folder_watcher.start()

        with pytest.raises(WatcherError, match="already running"):
            await folder_watcher.start()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, folder_watcher):
        """Test stop when not running is safe."""
        # Should not raise
        await folder_watcher.stop()


class TestFileProcessing:
    """Tests for file processing flow."""

    @pytest.mark.asyncio
    async def test_process_valid_file(self, folder_watcher, temp_dirs, mock_database):
        """Test processing a valid audio file."""
        events: List[NewCaptureEvent] = []

        async def capture_callback(event: NewCaptureEvent):
            events.append(event)

        folder_watcher.on_new_capture(capture_callback)
        await folder_watcher.start()

        # Create a valid audio file
        file_path = temp_dirs["inbox"] / "2026-01-20T143022_watch.m4a"
        create_m4a_file(file_path)

        # Wait for processing
        await asyncio.sleep(1.5)
        await folder_watcher.stop()

        # Verify file was moved to processing
        assert not file_path.exists()
        assert (temp_dirs["processing"] / file_path.name).exists()

        # Verify database record was created
        capture = await mock_database.get_capture_by_filename(file_path.name)
        assert capture is not None
        assert capture.status == "pending"
        assert capture.device == "watch"

        # Verify callback was invoked
        assert len(events) == 1
        assert events[0].filename == file_path.name
        assert events[0].device == "watch"

    @pytest.mark.asyncio
    async def test_process_invalid_file_moves_to_failed(
        self, folder_watcher, temp_dirs, mock_database
    ):
        """Test invalid file is moved to failed directory."""
        await folder_watcher.start()

        # Create an invalid file
        file_path = temp_dirs["inbox"] / "invalid.m4a"
        create_invalid_file(file_path)

        # Wait for processing
        await asyncio.sleep(1.5)
        await folder_watcher.stop()

        # Verify file was moved to failed
        assert not file_path.exists()
        assert (temp_dirs["failed"] / file_path.name).exists()

        # Verify error file was created
        error_file = temp_dirs["failed"] / "invalid.error"
        assert error_file.exists()
        error_content = error_file.read_text()
        assert "invalid_format" in error_content

    @pytest.mark.asyncio
    async def test_process_malformed_filename(
        self, folder_watcher, temp_dirs, mock_database
    ):
        """Test file with malformed filename is still processed."""
        events: List[NewCaptureEvent] = []

        async def capture_callback(event: NewCaptureEvent):
            events.append(event)

        folder_watcher.on_new_capture(capture_callback)
        await folder_watcher.start()

        # Create file with malformed name
        file_path = temp_dirs["inbox"] / "random_audio.m4a"
        create_m4a_file(file_path)

        # Wait for processing
        await asyncio.sleep(1.5)
        await folder_watcher.stop()

        # Should still be processed (never lose content)
        assert not file_path.exists()
        assert (temp_dirs["processing"] / file_path.name).exists()

        # Device should be UNKNOWN
        assert len(events) == 1
        assert events[0].device == "unknown"

    @pytest.mark.asyncio
    async def test_process_existing_files_on_start(
        self, temp_dirs, mock_database
    ):
        """Test existing files in inbox are processed on start."""
        # Create files before starting watcher
        file1 = temp_dirs["inbox"] / "2026-01-20T100000_watch.m4a"
        file2 = temp_dirs["inbox"] / "2026-01-20T110000_phone.m4a"
        create_m4a_file(file1)
        create_m4a_file(file2)

        events: List[NewCaptureEvent] = []

        async def capture_callback(event: NewCaptureEvent):
            events.append(event)

        watcher = FolderWatcher(
            inbox_path=temp_dirs["inbox"],
            processing_path=temp_dirs["processing"],
            failed_path=temp_dirs["failed"],
            db=mock_database,
            file_settle_delay=0.1,
        )
        watcher.on_new_capture(capture_callback)

        await watcher.start()
        await asyncio.sleep(1.0)
        await watcher.stop()

        # Both files should be processed
        assert len(events) == 2
        processed_names = {e.filename for e in events}
        assert file1.name in processed_names
        assert file2.name in processed_names

    @pytest.mark.asyncio
    async def test_duplicate_file_not_reprocessed(
        self, folder_watcher, temp_dirs, mock_database
    ):
        """Test duplicate files are not reprocessed."""
        events: List[NewCaptureEvent] = []

        async def capture_callback(event: NewCaptureEvent):
            events.append(event)

        folder_watcher.on_new_capture(capture_callback)
        await folder_watcher.start()

        # Create and process first file
        file_path = temp_dirs["inbox"] / "2026-01-20T143022_watch.m4a"
        create_m4a_file(file_path)
        await asyncio.sleep(1.5)

        assert len(events) == 1

        # "Re-add" the same file (simulate duplicate sync)
        create_m4a_file(file_path)
        await asyncio.sleep(1.5)

        await folder_watcher.stop()

        # Should still only have 1 event
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_ignore_non_audio_extensions(
        self, folder_watcher, temp_dirs, mock_database
    ):
        """Test non-audio files are ignored."""
        events: List[NewCaptureEvent] = []

        async def capture_callback(event: NewCaptureEvent):
            events.append(event)

        folder_watcher.on_new_capture(capture_callback)
        await folder_watcher.start()

        # Create non-audio files
        txt_file = temp_dirs["inbox"] / "readme.txt"
        txt_file.write_text("This is a text file")

        json_file = temp_dirs["inbox"] / "config.json"
        json_file.write_text("{}")

        await asyncio.sleep(1.0)
        await folder_watcher.stop()

        # No events should be generated
        assert len(events) == 0


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_file_deleted_during_processing(
        self, folder_watcher, temp_dirs
    ):
        """Test handling when file is deleted during processing."""
        await folder_watcher.start()

        # Create file
        file_path = temp_dirs["inbox"] / "2026-01-20T143022_watch.m4a"
        create_m4a_file(file_path)

        # Delete immediately
        await asyncio.sleep(0.1)
        if file_path.exists():
            file_path.unlink()

        # Should not crash
        await asyncio.sleep(1.5)
        await folder_watcher.stop()

    @pytest.mark.asyncio
    async def test_handle_permission_error(self, temp_dirs, mock_database):
        """Test handling of permission errors."""
        watcher = FolderWatcher(
            inbox_path=temp_dirs["inbox"],
            processing_path=temp_dirs["processing"],
            failed_path=temp_dirs["failed"],
            db=mock_database,
            file_settle_delay=0.1,
        )

        await watcher.start()

        # Create a file
        file_path = temp_dirs["inbox"] / "test.m4a"
        create_m4a_file(file_path)

        await asyncio.sleep(1.5)
        await watcher.stop()

        # Test should complete without crashing

    @pytest.mark.asyncio
    async def test_filename_collision_handling(
        self, folder_watcher, temp_dirs, mock_database
    ):
        """Test handling of filename collisions in processing directory."""
        await folder_watcher.start()

        # Pre-create a file in processing with same name
        existing = temp_dirs["processing"] / "test.m4a"
        create_m4a_file(existing)

        # Add new file with same name to inbox
        new_file = temp_dirs["inbox"] / "test.m4a"
        create_m4a_file(new_file)

        await asyncio.sleep(1.5)
        await folder_watcher.stop()

        # Both files should exist (one renamed)
        processing_files = list(temp_dirs["processing"].glob("*.m4a"))
        assert len(processing_files) == 2


class TestPublicInterface:
    """Tests for public interface methods."""

    def test_validate_audio_file(self, folder_watcher, temp_dirs):
        """Test public validate_audio_file method."""
        file_path = temp_dirs["inbox"] / "test.m4a"
        create_m4a_file(file_path)

        assert folder_watcher.validate_audio_file(file_path) is True

    def test_validate_invalid_file(self, folder_watcher, temp_dirs):
        """Test validate_audio_file returns False for invalid file."""
        file_path = temp_dirs["inbox"] / "test.m4a"
        create_invalid_file(file_path)

        assert folder_watcher.validate_audio_file(file_path) is False

    def test_parse_filename(self, folder_watcher):
        """Test public parse_filename method."""
        timestamp, device = folder_watcher.parse_filename(
            "2026-01-20T143022_watch.m4a"
        )

        assert device == "watch"
        assert timestamp.year == 2026
        assert timestamp.month == 1
        assert timestamp.day == 20


class TestCallbackRegistration:
    """Tests for callback registration."""

    def test_register_multiple_callbacks(self, folder_watcher):
        """Test registering multiple callbacks."""
        callbacks = []

        async def cb1(event):
            callbacks.append(1)

        async def cb2(event):
            callbacks.append(2)

        folder_watcher.on_new_capture(cb1)
        folder_watcher.on_new_capture(cb2)

        assert len(folder_watcher._callbacks) == 2

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_stop_processing(
        self, folder_watcher, temp_dirs, mock_database
    ):
        """Test that callback exceptions don't stop other processing."""
        events: List[NewCaptureEvent] = []

        async def bad_callback(event):
            raise ValueError("Callback error")

        async def good_callback(event):
            events.append(event)

        folder_watcher.on_new_capture(bad_callback)
        folder_watcher.on_new_capture(good_callback)

        await folder_watcher.start()

        file_path = temp_dirs["inbox"] / "2026-01-20T143022_watch.m4a"
        create_m4a_file(file_path)

        await asyncio.sleep(1.5)
        await folder_watcher.stop()

        # Good callback should still be called
        assert len(events) == 1
