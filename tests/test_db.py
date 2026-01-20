"""Unit tests for the SQLite database layer.

Tests all CRUD operations for captures, failure_log, and daily_stats tables.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from src.db.database import Database, VALID_STATUSES
from src.db.models import CaptureRow, DailyStatsRow, FailureLogRow


@pytest_asyncio.fixture
async def db(temp_dir: Path) -> Database:
    """Create a test database instance."""
    db_path = temp_dir / "test.db"
    database = Database(db_path)
    await database.initialize()
    yield database
    await database.close()


class TestDatabaseInitialization:
    """Tests for database initialization."""

    @pytest.mark.asyncio
    async def test_initialize_creates_database_file(self, temp_dir: Path) -> None:
        """Database file is created on initialization."""
        db_path = temp_dir / "new.db"
        assert not db_path.exists()

        db = Database(db_path)
        await db.initialize()

        assert db_path.exists()
        await db.close()

    @pytest.mark.asyncio
    async def test_initialize_creates_parent_directory(self, temp_dir: Path) -> None:
        """Parent directories are created if they don't exist."""
        db_path = temp_dir / "nested" / "path" / "test.db"
        assert not db_path.parent.exists()

        db = Database(db_path)
        await db.initialize()

        assert db_path.exists()
        await db.close()

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, db: Database) -> None:
        """All required tables are created."""
        async with db._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = {row["name"] for row in await cursor.fetchall()}

        assert "captures" in tables
        assert "failure_log" in tables
        assert "daily_stats" in tables

    @pytest.mark.asyncio
    async def test_initialize_creates_indexes(self, db: Database) -> None:
        """All required indexes are created."""
        async with db._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
            )
            indexes = {row["name"] for row in await cursor.fetchall()}

        assert "idx_captures_status" in indexes
        assert "idx_captures_captured_at" in indexes
        assert "idx_failure_log_capture_id" in indexes

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, db: Database) -> None:
        """Calling initialize multiple times is safe."""
        # Initialize is already called in fixture
        await db.initialize()  # Should not raise
        await db.initialize()  # Should not raise

    @pytest.mark.asyncio
    async def test_context_manager(self, temp_dir: Path) -> None:
        """Database works as async context manager."""
        db_path = temp_dir / "context.db"

        async with Database(db_path) as db:
            capture_id = await db.insert_capture(
                filename="test.m4a",
                original_path="/path/test.m4a",
            )
            assert capture_id > 0

        # Database should be closed after context exit
        assert db._pool.empty()


class TestCaptureOperations:
    """Tests for capture CRUD operations."""

    @pytest.mark.asyncio
    async def test_insert_capture_basic(self, db: Database) -> None:
        """Insert a basic capture record."""
        capture_id = await db.insert_capture(
            filename="2026-01-20T143022_watch.m4a",
            original_path="/inbox/2026-01-20T143022_watch.m4a",
        )

        assert capture_id > 0

        capture = await db.get_capture_by_id(capture_id)
        assert capture is not None
        assert capture.filename == "2026-01-20T143022_watch.m4a"
        assert capture.original_path == "/inbox/2026-01-20T143022_watch.m4a"
        assert capture.status == "pending"
        assert capture.retry_count == 0

    @pytest.mark.asyncio
    async def test_insert_capture_with_all_fields(self, db: Database) -> None:
        """Insert a capture with all optional fields."""
        captured_at = datetime(2026, 1, 20, 14, 30, 22)

        capture_id = await db.insert_capture(
            filename="test.m4a",
            original_path="/inbox/test.m4a",
            device="watch",
            captured_at=captured_at,
            current_path="/processing/test.m4a",
        )

        capture = await db.get_capture_by_id(capture_id)
        assert capture is not None
        assert capture.device == "watch"
        assert capture.captured_at == captured_at
        assert capture.current_path == "/processing/test.m4a"

    @pytest.mark.asyncio
    async def test_insert_capture_duplicate_filename_fails(self, db: Database) -> None:
        """Inserting duplicate filename raises error."""
        await db.insert_capture(
            filename="duplicate.m4a",
            original_path="/inbox/duplicate.m4a",
        )

        with pytest.raises(Exception):  # sqlite3.IntegrityError
            await db.insert_capture(
                filename="duplicate.m4a",
                original_path="/other/duplicate.m4a",
            )

    @pytest.mark.asyncio
    async def test_get_capture_by_id_not_found(self, db: Database) -> None:
        """Getting non-existent capture returns None."""
        capture = await db.get_capture_by_id(99999)
        assert capture is None

    @pytest.mark.asyncio
    async def test_get_capture_by_filename(self, db: Database) -> None:
        """Get capture by filename."""
        await db.insert_capture(
            filename="findme.m4a",
            original_path="/inbox/findme.m4a",
        )

        capture = await db.get_capture_by_filename("findme.m4a")
        assert capture is not None
        assert capture.filename == "findme.m4a"

    @pytest.mark.asyncio
    async def test_get_capture_by_filename_not_found(self, db: Database) -> None:
        """Getting non-existent filename returns None."""
        capture = await db.get_capture_by_filename("nonexistent.m4a")
        assert capture is None

    @pytest.mark.asyncio
    async def test_update_status(self, db: Database) -> None:
        """Update capture status."""
        capture_id = await db.insert_capture(
            filename="status.m4a",
            original_path="/inbox/status.m4a",
        )

        result = await db.update_status(capture_id, "transcribing")
        assert result is True

        capture = await db.get_capture_by_id(capture_id)
        assert capture.status == "transcribing"
        assert capture.last_attempt_at is not None

    @pytest.mark.asyncio
    async def test_update_status_with_error(self, db: Database) -> None:
        """Update status with error message."""
        capture_id = await db.insert_capture(
            filename="error.m4a",
            original_path="/inbox/error.m4a",
        )

        await db.update_status(capture_id, "failed", error="API timeout")

        capture = await db.get_capture_by_id(capture_id)
        assert capture.status == "failed"
        assert capture.last_error == "API timeout"

    @pytest.mark.asyncio
    async def test_update_status_invalid_status(self, db: Database) -> None:
        """Updating with invalid status raises error."""
        capture_id = await db.insert_capture(
            filename="invalid.m4a",
            original_path="/inbox/invalid.m4a",
        )

        with pytest.raises(ValueError, match="Invalid status"):
            await db.update_status(capture_id, "invalid_status")

    @pytest.mark.asyncio
    async def test_update_status_not_found(self, db: Database) -> None:
        """Updating non-existent capture returns False."""
        result = await db.update_status(99999, "transcribing")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_pending_captures(self, db: Database) -> None:
        """Get all pending captures."""
        # Create captures with different statuses
        await db.insert_capture(filename="pending1.m4a", original_path="/inbox/pending1.m4a")
        await db.insert_capture(filename="pending2.m4a", original_path="/inbox/pending2.m4a")

        id3 = await db.insert_capture(filename="transcribing.m4a", original_path="/inbox/transcribing.m4a")
        await db.update_status(id3, "transcribing")

        pending = await db.get_pending_captures()
        assert len(pending) == 2
        assert all(c.status == "pending" for c in pending)

    @pytest.mark.asyncio
    async def test_get_captures_by_status(self, db: Database) -> None:
        """Get captures by any status."""
        id1 = await db.insert_capture(filename="t1.m4a", original_path="/inbox/t1.m4a")
        id2 = await db.insert_capture(filename="t2.m4a", original_path="/inbox/t2.m4a")
        await db.insert_capture(filename="p1.m4a", original_path="/inbox/p1.m4a")

        await db.update_status(id1, "transcribing")
        await db.update_status(id2, "transcribing")

        transcribing = await db.get_captures_by_status("transcribing")
        assert len(transcribing) == 2

    @pytest.mark.asyncio
    async def test_increment_retry(self, db: Database) -> None:
        """Increment retry count."""
        capture_id = await db.insert_capture(
            filename="retry.m4a",
            original_path="/inbox/retry.m4a",
        )

        # Initial count is 0
        capture = await db.get_capture_by_id(capture_id)
        assert capture.retry_count == 0

        # Increment
        new_count = await db.increment_retry(capture_id)
        assert new_count == 1

        new_count = await db.increment_retry(capture_id)
        assert new_count == 2

        capture = await db.get_capture_by_id(capture_id)
        assert capture.retry_count == 2

    @pytest.mark.asyncio
    async def test_increment_retry_not_found(self, db: Database) -> None:
        """Incrementing retry for non-existent capture raises error."""
        with pytest.raises(ValueError, match="Capture not found"):
            await db.increment_retry(99999)

    @pytest.mark.asyncio
    async def test_update_transcription(self, db: Database) -> None:
        """Update transcription results."""
        capture_id = await db.insert_capture(
            filename="transcribe.m4a",
            original_path="/inbox/transcribe.m4a",
        )

        result = await db.update_transcription(
            capture_id=capture_id,
            transcript="This is the transcribed text.",
            duration=45.5,
            language="en",
        )
        assert result is True

        capture = await db.get_capture_by_id(capture_id)
        assert capture.transcript == "This is the transcribed text."
        assert capture.transcript_duration_seconds == 45.5
        assert capture.transcript_language == "en"

    @pytest.mark.asyncio
    async def test_update_classification(self, db: Database) -> None:
        """Update classification results."""
        capture_id = await db.insert_capture(
            filename="classify.m4a",
            original_path="/inbox/classify.m4a",
        )

        fields = {"priority": "High", "context": "Project meeting"}
        tags = ["work", "meeting"]

        result = await db.update_classification(
            capture_id=capture_id,
            template="task",
            confidence=0.85,
            fields=fields,
            title="Review quarterly report",
            tags=tags,
        )
        assert result is True

        capture = await db.get_capture_by_id(capture_id)
        assert capture.template_name == "task"
        assert capture.classification_confidence == 0.85
        assert capture.extracted_fields == fields
        assert capture.suggested_title == "Review quarterly report"
        assert capture.tags == tags

    @pytest.mark.asyncio
    async def test_update_notion_result(self, db: Database) -> None:
        """Update Notion page information."""
        capture_id = await db.insert_capture(
            filename="notion.m4a",
            original_path="/inbox/notion.m4a",
        )

        result = await db.update_notion_result(
            capture_id=capture_id,
            page_id="abc-123-def",
            page_url="https://notion.so/abc-123-def",
        )
        assert result is True

        capture = await db.get_capture_by_id(capture_id)
        assert capture.notion_page_id == "abc-123-def"
        assert capture.notion_page_url == "https://notion.so/abc-123-def"

    @pytest.mark.asyncio
    async def test_mark_complete(self, db: Database) -> None:
        """Mark capture as complete."""
        capture_id = await db.insert_capture(
            filename="complete.m4a",
            original_path="/inbox/complete.m4a",
        )

        result = await db.mark_complete(capture_id)
        assert result is True

        capture = await db.get_capture_by_id(capture_id)
        assert capture.status == "complete"
        assert capture.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_current_path(self, db: Database) -> None:
        """Update current file path."""
        capture_id = await db.insert_capture(
            filename="move.m4a",
            original_path="/inbox/move.m4a",
        )

        result = await db.update_current_path(capture_id, "/processing/move.m4a")
        assert result is True

        capture = await db.get_capture_by_id(capture_id)
        assert capture.current_path == "/processing/move.m4a"

    @pytest.mark.asyncio
    async def test_reset_capture(self, db: Database) -> None:
        """Reset capture to pending status."""
        capture_id = await db.insert_capture(
            filename="reset.m4a",
            original_path="/inbox/reset.m4a",
        )

        # Set to failed with retries
        await db.update_status(capture_id, "failed", error="Some error")
        await db.increment_retry(capture_id)
        await db.increment_retry(capture_id)

        # Reset
        result = await db.reset_capture(capture_id)
        assert result is True

        capture = await db.get_capture_by_id(capture_id)
        assert capture.status == "pending"
        assert capture.retry_count == 0
        assert capture.last_error is None

    @pytest.mark.asyncio
    async def test_delete_capture(self, db: Database) -> None:
        """Delete a capture."""
        capture_id = await db.insert_capture(
            filename="delete.m4a",
            original_path="/inbox/delete.m4a",
        )

        # Add some failure logs
        await db.log_failure(capture_id, "transcribing", error_message="Test error")

        # Delete
        result = await db.delete_capture(capture_id)
        assert result is True

        # Verify deleted
        capture = await db.get_capture_by_id(capture_id)
        assert capture is None

        # Verify failure logs also deleted
        failures = await db.get_failures_for_capture(capture_id)
        assert len(failures) == 0

    @pytest.mark.asyncio
    async def test_get_captures_by_date_range(self, db: Database) -> None:
        """Get captures within date range."""
        dates = [
            datetime(2026, 1, 15),
            datetime(2026, 1, 20),
            datetime(2026, 1, 25),
        ]

        for i, date in enumerate(dates):
            await db.insert_capture(
                filename=f"date{i}.m4a",
                original_path=f"/inbox/date{i}.m4a",
                captured_at=date,
            )

        # Query middle range
        captures = await db.get_captures_by_date_range(
            start_date=datetime(2026, 1, 18),
            end_date=datetime(2026, 1, 22),
        )
        assert len(captures) == 1
        assert captures[0].filename == "date1.m4a"

    @pytest.mark.asyncio
    async def test_get_queue_depth(self, db: Database) -> None:
        """Get count of captures by status."""
        # Create captures with different statuses
        await db.insert_capture(filename="p1.m4a", original_path="/inbox/p1.m4a")
        await db.insert_capture(filename="p2.m4a", original_path="/inbox/p2.m4a")

        id3 = await db.insert_capture(filename="t1.m4a", original_path="/inbox/t1.m4a")
        await db.update_status(id3, "transcribing")

        id4 = await db.insert_capture(filename="c1.m4a", original_path="/inbox/c1.m4a")
        await db.mark_complete(id4)

        depths = await db.get_queue_depth()
        assert depths["pending"] == 2
        assert depths["transcribing"] == 1
        assert depths["complete"] == 1


class TestFailureLogOperations:
    """Tests for failure_log CRUD operations."""

    @pytest.mark.asyncio
    async def test_log_failure_basic(self, db: Database) -> None:
        """Log a basic failure."""
        capture_id = await db.insert_capture(
            filename="fail.m4a",
            original_path="/inbox/fail.m4a",
        )

        log_id = await db.log_failure(
            capture_id=capture_id,
            stage="transcribing",
            error_message="API timeout",
        )

        assert log_id > 0

    @pytest.mark.asyncio
    async def test_log_failure_with_details(self, db: Database) -> None:
        """Log failure with all fields."""
        capture_id = await db.insert_capture(
            filename="detail.m4a",
            original_path="/inbox/detail.m4a",
        )

        details = {"status_code": 429, "retry_after": 60}

        log_id = await db.log_failure(
            capture_id=capture_id,
            stage="posting",
            error_type="RateLimitError",
            error_message="Too many requests",
            error_details=details,
        )

        failures = await db.get_failures_for_capture(capture_id)
        assert len(failures) == 1

        failure = failures[0]
        assert failure.stage == "posting"
        assert failure.error_type == "RateLimitError"
        assert failure.error_message == "Too many requests"
        assert failure.error_details == details
        assert failure.occurred_at is not None

    @pytest.mark.asyncio
    async def test_get_failures_for_capture(self, db: Database) -> None:
        """Get all failures for a capture."""
        capture_id = await db.insert_capture(
            filename="multi.m4a",
            original_path="/inbox/multi.m4a",
        )

        # Log multiple failures
        await db.log_failure(capture_id, "transcribing", error_message="Error 1")
        await db.log_failure(capture_id, "transcribing", error_message="Error 2")
        await db.log_failure(capture_id, "classifying", error_message="Error 3")

        failures = await db.get_failures_for_capture(capture_id)
        assert len(failures) == 3
        assert failures[0].error_message == "Error 1"
        assert failures[2].stage == "classifying"

    @pytest.mark.asyncio
    async def test_get_failures_empty(self, db: Database) -> None:
        """Get failures for capture with no failures."""
        capture_id = await db.insert_capture(
            filename="success.m4a",
            original_path="/inbox/success.m4a",
        )

        failures = await db.get_failures_for_capture(capture_id)
        assert len(failures) == 0


class TestDailyStatsOperations:
    """Tests for daily_stats CRUD operations."""

    @pytest.mark.asyncio
    async def test_get_daily_stats_not_found(self, db: Database) -> None:
        """Getting stats for date with no data returns None."""
        stats = await db.get_daily_stats("2026-01-20")
        assert stats is None

    @pytest.mark.asyncio
    async def test_update_daily_stats_create(self, db: Database) -> None:
        """Create new daily stats."""
        result = await db.update_daily_stats(
            date="2026-01-20",
            captures_received=5,
            captures_completed=4,
            captures_failed=1,
            total_audio_seconds=250.5,
            avg_processing_time_seconds=30.2,
            template_breakdown={"task": 2, "journal": 3},
        )
        assert result is True

        stats = await db.get_daily_stats("2026-01-20")
        assert stats is not None
        assert stats.captures_received == 5
        assert stats.captures_completed == 4
        assert stats.captures_failed == 1
        assert stats.total_audio_seconds == 250.5
        assert stats.avg_processing_time_seconds == 30.2
        assert stats.template_breakdown == {"task": 2, "journal": 3}

    @pytest.mark.asyncio
    async def test_update_daily_stats_partial_update(self, db: Database) -> None:
        """Partial update preserves existing values."""
        # Create initial stats
        await db.update_daily_stats(
            date="2026-01-21",
            captures_received=10,
            captures_completed=8,
        )

        # Partial update
        await db.update_daily_stats(
            date="2026-01-21",
            captures_failed=2,
        )

        stats = await db.get_daily_stats("2026-01-21")
        assert stats.captures_received == 10  # Preserved
        assert stats.captures_completed == 8  # Preserved
        assert stats.captures_failed == 2  # Updated

    @pytest.mark.asyncio
    async def test_increment_daily_stat(self, db: Database) -> None:
        """Increment daily stat atomically."""
        date = "2026-01-22"

        # First increment creates the row
        new_value = await db.increment_daily_stat(date, "captures_received")
        assert new_value == 1

        # Additional increments
        new_value = await db.increment_daily_stat(date, "captures_received")
        assert new_value == 2

        new_value = await db.increment_daily_stat(date, "captures_completed", amount=3)
        assert new_value == 3

        stats = await db.get_daily_stats(date)
        assert stats.captures_received == 2
        assert stats.captures_completed == 3

    @pytest.mark.asyncio
    async def test_increment_daily_stat_invalid_field(self, db: Database) -> None:
        """Incrementing invalid field raises error."""
        with pytest.raises(ValueError, match="Invalid field"):
            await db.increment_daily_stat("2026-01-23", "invalid_field")

    @pytest.mark.asyncio
    async def test_get_stats_for_date_range(self, db: Database) -> None:
        """Get stats for date range."""
        dates = ["2026-01-18", "2026-01-19", "2026-01-20", "2026-01-21"]

        for i, date in enumerate(dates):
            await db.update_daily_stats(date=date, captures_received=i + 1)

        stats = await db.get_stats_for_date_range("2026-01-19", "2026-01-20")
        assert len(stats) == 2
        assert stats[0].date == "2026-01-19"
        assert stats[0].captures_received == 2
        assert stats[1].date == "2026-01-20"
        assert stats[1].captures_received == 3


class TestConcurrency:
    """Tests for concurrent database access."""

    @pytest.mark.asyncio
    async def test_concurrent_inserts(self, db: Database) -> None:
        """Multiple concurrent inserts work correctly."""
        async def insert_capture(i: int) -> int:
            return await db.insert_capture(
                filename=f"concurrent_{i}.m4a",
                original_path=f"/inbox/concurrent_{i}.m4a",
            )

        # Insert 10 captures concurrently
        ids = await asyncio.gather(*[insert_capture(i) for i in range(10)])

        assert len(ids) == 10
        assert len(set(ids)) == 10  # All unique IDs

    @pytest.mark.asyncio
    async def test_concurrent_reads_writes(self, db: Database) -> None:
        """Concurrent reads and writes work correctly."""
        capture_id = await db.insert_capture(
            filename="concurrent.m4a",
            original_path="/inbox/concurrent.m4a",
        )

        async def read() -> CaptureRow:
            return await db.get_capture_by_id(capture_id)

        async def write(status: str) -> bool:
            return await db.update_status(capture_id, status)

        # Mix of reads and writes
        results = await asyncio.gather(
            read(),
            write("transcribing"),
            read(),
            read(),
        )

        # All operations should complete
        assert len(results) == 4


class TestDataModels:
    """Tests for database row models."""

    def test_capture_row_from_row(self) -> None:
        """CaptureRow.from_row handles all field types."""
        row = {
            "id": 1,
            "filename": "test.m4a",
            "original_path": "/inbox/test.m4a",
            "current_path": "/processing/test.m4a",
            "device": "watch",
            "captured_at": "2026-01-20T14:30:22",
            "status": "pending",
            "retry_count": 2,
            "last_error": "Test error",
            "last_attempt_at": "2026-01-20T15:00:00",
            "transcript": "Hello world",
            "transcript_duration_seconds": 5.5,
            "transcript_language": "en",
            "template_name": "task",
            "classification_confidence": 0.85,
            "extracted_fields": '{"priority": "High"}',
            "suggested_title": "Test task",
            "tags": '["work", "test"]',
            "notion_page_id": "abc123",
            "notion_page_url": "https://notion.so/abc123",
            "created_at": "2026-01-20T14:30:00",
            "updated_at": "2026-01-20T15:00:00",
            "completed_at": None,
        }

        capture = CaptureRow.from_row(row)

        assert capture.id == 1
        assert capture.filename == "test.m4a"
        assert capture.device == "watch"
        assert capture.captured_at == datetime(2026, 1, 20, 14, 30, 22)
        assert capture.retry_count == 2
        assert capture.extracted_fields == {"priority": "High"}
        assert capture.tags == ["work", "test"]

    def test_capture_row_handles_none_values(self) -> None:
        """CaptureRow.from_row handles None values."""
        row = {
            "id": 1,
            "filename": "test.m4a",
            "original_path": "/inbox/test.m4a",
            "current_path": None,
            "device": None,
            "captured_at": None,
            "status": "pending",
            "retry_count": 0,
            "last_error": None,
            "last_attempt_at": None,
            "transcript": None,
            "transcript_duration_seconds": None,
            "transcript_language": None,
            "template_name": None,
            "classification_confidence": None,
            "extracted_fields": None,
            "suggested_title": None,
            "tags": None,
            "notion_page_id": None,
            "notion_page_url": None,
            "created_at": None,
            "updated_at": None,
            "completed_at": None,
        }

        capture = CaptureRow.from_row(row)

        assert capture.current_path is None
        assert capture.device is None
        assert capture.captured_at is None
        assert capture.extracted_fields is None
        assert capture.tags is None

    def test_failure_log_row_from_row(self) -> None:
        """FailureLogRow.from_row handles all field types."""
        row = {
            "id": 1,
            "capture_id": 42,
            "stage": "transcribing",
            "error_type": "TimeoutError",
            "error_message": "Request timed out",
            "error_details": '{"timeout": 120}',
            "occurred_at": "2026-01-20T15:00:00",
        }

        failure = FailureLogRow.from_row(row)

        assert failure.id == 1
        assert failure.capture_id == 42
        assert failure.stage == "transcribing"
        assert failure.error_details == {"timeout": 120}
        assert failure.occurred_at == datetime(2026, 1, 20, 15, 0, 0)

    def test_daily_stats_row_from_row(self) -> None:
        """DailyStatsRow.from_row handles all field types."""
        row = {
            "date": "2026-01-20",
            "captures_received": 10,
            "captures_completed": 8,
            "captures_failed": 2,
            "total_audio_seconds": 500.0,
            "avg_processing_time_seconds": 30.5,
            "template_breakdown": '{"task": 5, "journal": 3}',
        }

        stats = DailyStatsRow.from_row(row)

        assert stats.date == "2026-01-20"
        assert stats.captures_received == 10
        assert stats.template_breakdown == {"task": 5, "journal": 3}
