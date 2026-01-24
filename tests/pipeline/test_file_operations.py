"""Unit tests for the FileOperations helper class.

Tests cover:
- Move to processing operation
- Move to failed operation
- Delete on success operation
- Error handling for all operations
- Name conflict handling
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.pipeline.file_operations import FileOperations, PathConfig


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing file operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        inbox = base / "inbox"
        processing = base / "processing"
        failed = base / "failed"

        # Create all directories
        inbox.mkdir()
        processing.mkdir()
        failed.mkdir()

        yield {
            "base": base,
            "inbox": inbox,
            "processing": processing,
            "failed": failed,
        }


@pytest.fixture
def path_config(temp_dirs):
    """Create a PathConfig with temp directories."""
    return PathConfig(
        inbox=temp_dirs["inbox"],
        processing=temp_dirs["processing"],
        failed=temp_dirs["failed"],
    )


@pytest.fixture
def mock_db():
    """Create a mock database with update_current_path method."""
    db = MagicMock()
    db.update_current_path = AsyncMock(return_value=True)
    return db


@pytest.fixture
def file_ops(path_config, mock_db):
    """Create a FileOperations instance with temp paths."""
    return FileOperations(paths=path_config, db=mock_db)


@pytest.fixture
def sample_file(temp_dirs):
    """Create a sample audio file in the inbox."""
    file_path = temp_dirs["inbox"] / "test_audio.m4a"
    file_path.write_bytes(b"fake audio content")
    return file_path


# =============================================================================
# Move to Processing Tests
# =============================================================================


class TestMoveToProcessing:
    """Tests for FileOperations.move_to_processing method."""

    @pytest.mark.asyncio
    async def test_move_to_processing_success(self, file_ops, sample_file, temp_dirs):
        """Verify file is moved to processing directory."""
        result = await file_ops.move_to_processing(sample_file, capture_id=1)

        assert result is not None
        assert result.parent == temp_dirs["processing"]
        assert result.name == "test_audio.m4a"
        assert result.exists()
        assert not sample_file.exists()

    @pytest.mark.asyncio
    async def test_move_to_processing_updates_database(
        self, file_ops, sample_file, mock_db
    ):
        """Verify database is updated with new path."""
        result = await file_ops.move_to_processing(sample_file, capture_id=42)

        mock_db.update_current_path.assert_called_once()
        call_args = mock_db.update_current_path.call_args
        assert call_args[0][0] == 42  # capture_id
        assert "processing" in call_args[0][1]  # new path

    @pytest.mark.asyncio
    async def test_move_to_processing_no_capture_id(
        self, file_ops, sample_file, mock_db
    ):
        """Verify no database update when capture_id is None."""
        result = await file_ops.move_to_processing(sample_file)

        assert result is not None
        mock_db.update_current_path.assert_not_called()

    @pytest.mark.asyncio
    async def test_move_to_processing_missing_file(self, file_ops, temp_dirs):
        """Verify None returned for missing file."""
        missing_file = temp_dirs["inbox"] / "nonexistent.m4a"
        result = await file_ops.move_to_processing(missing_file)

        assert result is None

    @pytest.mark.asyncio
    async def test_move_to_processing_handles_name_conflict(
        self, file_ops, temp_dirs
    ):
        """Verify name conflicts are handled by appending counter."""
        # Create source file
        source = temp_dirs["inbox"] / "test.m4a"
        source.write_bytes(b"source content")

        # Create existing file in processing with same name
        existing = temp_dirs["processing"] / "test.m4a"
        existing.write_bytes(b"existing content")

        result = await file_ops.move_to_processing(source)

        assert result is not None
        assert result.name == "test_1.m4a"
        assert result.exists()
        assert existing.exists()  # Original still there

    @pytest.mark.asyncio
    async def test_move_to_processing_creates_directory(self, temp_dirs, mock_db):
        """Verify processing directory is created if missing."""
        # Remove processing directory
        temp_dirs["processing"].rmdir()

        path_config = PathConfig(
            inbox=temp_dirs["inbox"],
            processing=temp_dirs["processing"],
            failed=temp_dirs["failed"],
        )
        file_ops = FileOperations(paths=path_config, db=mock_db)

        source = temp_dirs["inbox"] / "test.m4a"
        source.write_bytes(b"content")

        result = await file_ops.move_to_processing(source)

        assert result is not None
        assert temp_dirs["processing"].exists()


# =============================================================================
# Move to Failed Tests
# =============================================================================


class TestMoveToFailed:
    """Tests for FileOperations.move_to_failed method."""

    @pytest.mark.asyncio
    async def test_move_to_failed_success(self, file_ops, sample_file, temp_dirs):
        """Verify file is moved to failed directory."""
        result = await file_ops.move_to_failed(sample_file, capture_id=1)

        assert result is not None
        assert result.parent == temp_dirs["failed"]
        assert result.name == "test_audio.m4a"
        assert result.exists()
        assert not sample_file.exists()

    @pytest.mark.asyncio
    async def test_move_to_failed_updates_database(
        self, file_ops, sample_file, mock_db
    ):
        """Verify database is updated with new path."""
        result = await file_ops.move_to_failed(sample_file, capture_id=42)

        mock_db.update_current_path.assert_called_once()
        call_args = mock_db.update_current_path.call_args
        assert call_args[0][0] == 42  # capture_id
        assert "failed" in call_args[0][1]  # new path

    @pytest.mark.asyncio
    async def test_move_to_failed_no_capture_id(self, file_ops, sample_file, mock_db):
        """Verify no database update when capture_id is None."""
        result = await file_ops.move_to_failed(sample_file)

        assert result is not None
        mock_db.update_current_path.assert_not_called()

    @pytest.mark.asyncio
    async def test_move_to_failed_missing_file(self, file_ops, temp_dirs):
        """Verify None returned for missing file."""
        missing_file = temp_dirs["inbox"] / "nonexistent.m4a"
        result = await file_ops.move_to_failed(missing_file)

        assert result is None

    @pytest.mark.asyncio
    async def test_move_to_failed_creates_directory(self, temp_dirs, mock_db):
        """Verify failed directory is created if missing."""
        # Remove failed directory
        temp_dirs["failed"].rmdir()

        path_config = PathConfig(
            inbox=temp_dirs["inbox"],
            processing=temp_dirs["processing"],
            failed=temp_dirs["failed"],
        )
        file_ops = FileOperations(paths=path_config, db=mock_db)

        source = temp_dirs["inbox"] / "test.m4a"
        source.write_bytes(b"content")

        result = await file_ops.move_to_failed(source)

        assert result is not None
        assert temp_dirs["failed"].exists()


# =============================================================================
# Delete on Success Tests
# =============================================================================


class TestDeleteOnSuccess:
    """Tests for FileOperations.delete_on_success method."""

    @pytest.mark.asyncio
    async def test_delete_on_success_removes_file(self, file_ops, sample_file):
        """Verify file is deleted successfully."""
        assert sample_file.exists()

        result = await file_ops.delete_on_success(sample_file)

        assert result is True
        assert not sample_file.exists()

    @pytest.mark.asyncio
    async def test_delete_on_success_missing_file(self, file_ops, temp_dirs):
        """Verify True returned for already-deleted file."""
        missing_file = temp_dirs["inbox"] / "nonexistent.m4a"

        result = await file_ops.delete_on_success(missing_file)

        # Already deleted is considered success
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_on_success_directory_not_deleted(
        self, file_ops, temp_dirs
    ):
        """Verify directories are not deleted (returns False)."""
        directory = temp_dirs["inbox"] / "subdir"
        directory.mkdir()

        result = await file_ops.delete_on_success(directory)

        # Should fail to delete directory
        assert result is False
        assert directory.exists()


# =============================================================================
# Factory Method Tests
# =============================================================================


class TestFromFailedPath:
    """Tests for FileOperations.from_failed_path factory method."""

    def test_from_failed_path_creates_instance(self, temp_dirs, mock_db):
        """Verify factory creates valid instance."""
        file_ops = FileOperations.from_failed_path(
            failed_path=temp_dirs["failed"],
            db=mock_db,
        )

        assert file_ops.failed_path == temp_dirs["failed"]
        assert file_ops.processing_path == Path("/app/processing")
        assert file_ops.inbox_path == Path("/app/inbox")

    def test_from_failed_path_without_db(self, temp_dirs):
        """Verify factory works without database."""
        file_ops = FileOperations.from_failed_path(
            failed_path=temp_dirs["failed"],
        )

        assert file_ops.failed_path == temp_dirs["failed"]


# =============================================================================
# Is In Failed Directory Tests
# =============================================================================


class TestIsInFailedDirectory:
    """Tests for FileOperations.is_in_failed_directory method."""

    def test_file_in_failed_directory(self, file_ops, temp_dirs):
        """Verify True for file in failed directory."""
        file_path = temp_dirs["failed"] / "test.m4a"
        file_path.touch()

        result = file_ops.is_in_failed_directory(file_path)

        assert result is True

    def test_file_in_failed_subdirectory(self, file_ops, temp_dirs):
        """Verify True for file in subdirectory of failed."""
        subdir = temp_dirs["failed"] / "subdir"
        subdir.mkdir()
        file_path = subdir / "test.m4a"
        file_path.touch()

        result = file_ops.is_in_failed_directory(file_path)

        assert result is True

    def test_file_not_in_failed_directory(self, file_ops, temp_dirs):
        """Verify False for file in inbox."""
        file_path = temp_dirs["inbox"] / "test.m4a"
        file_path.touch()

        result = file_ops.is_in_failed_directory(file_path)

        assert result is False

    def test_file_in_processing_directory(self, file_ops, temp_dirs):
        """Verify False for file in processing."""
        file_path = temp_dirs["processing"] / "test.m4a"
        file_path.touch()

        result = file_ops.is_in_failed_directory(file_path)

        assert result is False


# =============================================================================
# Property Tests
# =============================================================================


class TestProperties:
    """Tests for FileOperations property methods."""

    def test_failed_path_property(self, file_ops, temp_dirs):
        """Verify failed_path property returns correct path."""
        assert file_ops.failed_path == temp_dirs["failed"]

    def test_processing_path_property(self, file_ops, temp_dirs):
        """Verify processing_path property returns correct path."""
        assert file_ops.processing_path == temp_dirs["processing"]

    def test_inbox_path_property(self, file_ops, temp_dirs):
        """Verify inbox_path property returns correct path."""
        assert file_ops.inbox_path == temp_dirs["inbox"]
