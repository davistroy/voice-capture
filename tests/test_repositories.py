"""Unit tests for the repository pattern implementation.

Tests all repository classes directly (CaptureRepository, FailureLogRepository,
StatisticsRepository) as well as the connection pool.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio

from src.db.connection import ConnectionPool, SCHEMA_SQL, VALID_STATUSES
from src.db.models import CaptureRow, DailyStatsRow, FailureLogRow
from src.db.repositories import (
    BaseRepository,
    CaptureRepository,
    FailureLogRepository,
    StatisticsRepository,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def pool(temp_dir: Path) -> ConnectionPool:
    """Create a test connection pool."""
    db_path = temp_dir / "test_repo.db"
    pool = ConnectionPool(db_path)
    await pool.initialize()
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def capture_repo(pool: ConnectionPool) -> CaptureRepository:
    """Create a CaptureRepository instance."""
    return CaptureRepository(pool)


@pytest_asyncio.fixture
async def failure_repo(pool: ConnectionPool) -> FailureLogRepository:
    """Create a FailureLogRepository instance."""
    return FailureLogRepository(pool)


@pytest_asyncio.fixture
async def stats_repo(pool: ConnectionPool) -> StatisticsRepository:
    """Create a StatisticsRepository instance."""
    return StatisticsRepository(pool)


# ============================================================================
# ConnectionPool Tests
# ============================================================================


class TestConnectionPool:
    """Tests for ConnectionPool class."""

    @pytest.mark.asyncio
    async def test_initialize_creates_database(self, temp_dir: Path) -> None:
        """Pool initialization creates database file."""
        db_path = temp_dir / "new_pool.db"
        assert not db_path.exists()

        pool = ConnectionPool(db_path)
        await pool.initialize()

        assert db_path.exists()
        assert pool.initialized
        await pool.close()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, pool: ConnectionPool) -> None:
        """Multiple initialize calls are safe."""
        await pool.initialize()
        await pool.initialize()
        assert pool.initialized

    @pytest.mark.asyncio
    async def test_acquire_before_init_raises(self, temp_dir: Path) -> None:
        """Acquiring connection before initialization raises error."""
        db_path = temp_dir / "uninitialized.db"
        pool = ConnectionPool(db_path)

        with pytest.raises(RuntimeError, match="not initialized"):
            async with pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_context_manager(self, temp_dir: Path) -> None:
        """Pool works as async context manager."""
        db_path = temp_dir / "context.db"

        async with ConnectionPool(db_path) as pool:
            async with pool.acquire() as conn:
                cursor = await conn.execute("SELECT 1")
                result = await cursor.fetchone()
                assert result[0] == 1

    @pytest.mark.asyncio
    async def test_close(self, temp_dir: Path) -> None:
        """Close releases all connections."""
        db_path = temp_dir / "close.db"
        pool = ConnectionPool(db_path)
        await pool.initialize()

        await pool.close()
        assert not pool.initialized


# ============================================================================
# CaptureRepository Tests
# ============================================================================


class TestCaptureRepository:
    """Tests for CaptureRepository class."""

    @pytest.mark.asyncio
    async def test_insert(self, capture_repo: CaptureRepository) -> None:
        """Insert a capture using repository."""
        capture_id = await capture_repo.insert(
            filename="test.m4a",
            original_path="/inbox/test.m4a",
            device="watch",
        )

        assert capture_id > 0

    @pytest.mark.asyncio
    async def test_get_by_id(self, capture_repo: CaptureRepository) -> None:
        """Get capture by ID."""
        capture_id = await capture_repo.insert(
            filename="byid.m4a",
            original_path="/inbox/byid.m4a",
        )

        capture = await capture_repo.get_by_id(capture_id)

        assert capture is not None
        assert capture.filename == "byid.m4a"
        assert capture.status == "pending"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, capture_repo: CaptureRepository) -> None:
        """Get non-existent capture returns None."""
        capture = await capture_repo.get_by_id(99999)
        assert capture is None

    @pytest.mark.asyncio
    async def test_get_by_filename(self, capture_repo: CaptureRepository) -> None:
        """Get capture by filename."""
        await capture_repo.insert(
            filename="findme.m4a",
            original_path="/inbox/findme.m4a",
        )

        capture = await capture_repo.get_by_filename("findme.m4a")

        assert capture is not None
        assert capture.filename == "findme.m4a"

    @pytest.mark.asyncio
    async def test_update_status(self, capture_repo: CaptureRepository) -> None:
        """Update capture status."""
        capture_id = await capture_repo.insert(
            filename="status.m4a",
            original_path="/inbox/status.m4a",
        )

        result = await capture_repo.update_status(capture_id, "transcribing")

        assert result is True
        capture = await capture_repo.get_by_id(capture_id)
        assert capture.status == "transcribing"

    @pytest.mark.asyncio
    async def test_update_status_invalid(self, capture_repo: CaptureRepository) -> None:
        """Invalid status raises ValueError."""
        capture_id = await capture_repo.insert(
            filename="invalid.m4a",
            original_path="/inbox/invalid.m4a",
        )

        with pytest.raises(ValueError, match="Invalid status"):
            await capture_repo.update_status(capture_id, "not_a_status")

    @pytest.mark.asyncio
    async def test_get_pending(self, capture_repo: CaptureRepository) -> None:
        """Get pending captures."""
        await capture_repo.insert(filename="p1.m4a", original_path="/inbox/p1.m4a")
        await capture_repo.insert(filename="p2.m4a", original_path="/inbox/p2.m4a")

        id3 = await capture_repo.insert(filename="t1.m4a", original_path="/inbox/t1.m4a")
        await capture_repo.update_status(id3, "transcribing")

        pending = await capture_repo.get_pending()

        assert len(pending) == 2
        assert all(c.status == "pending" for c in pending)

    @pytest.mark.asyncio
    async def test_get_by_status(self, capture_repo: CaptureRepository) -> None:
        """Get captures by status."""
        id1 = await capture_repo.insert(filename="s1.m4a", original_path="/inbox/s1.m4a")
        id2 = await capture_repo.insert(filename="s2.m4a", original_path="/inbox/s2.m4a")
        await capture_repo.update_status(id1, "classifying")
        await capture_repo.update_status(id2, "classifying")

        classifying = await capture_repo.get_by_status("classifying")

        assert len(classifying) == 2

    @pytest.mark.asyncio
    async def test_increment_retry(self, capture_repo: CaptureRepository) -> None:
        """Increment retry count."""
        capture_id = await capture_repo.insert(
            filename="retry.m4a",
            original_path="/inbox/retry.m4a",
        )

        new_count = await capture_repo.increment_retry(capture_id)
        assert new_count == 1

        new_count = await capture_repo.increment_retry(capture_id)
        assert new_count == 2

    @pytest.mark.asyncio
    async def test_update_transcription(self, capture_repo: CaptureRepository) -> None:
        """Update transcription results."""
        capture_id = await capture_repo.insert(
            filename="trans.m4a",
            original_path="/inbox/trans.m4a",
        )

        result = await capture_repo.update_transcription(
            capture_id=capture_id,
            transcript="Hello world",
            duration=10.5,
            language="en",
        )

        assert result is True
        capture = await capture_repo.get_by_id(capture_id)
        assert capture.transcript == "Hello world"
        assert capture.transcript_duration_seconds == 10.5
        assert capture.transcript_language == "en"

    @pytest.mark.asyncio
    async def test_update_classification(self, capture_repo: CaptureRepository) -> None:
        """Update classification results."""
        capture_id = await capture_repo.insert(
            filename="class.m4a",
            original_path="/inbox/class.m4a",
        )

        result = await capture_repo.update_classification(
            capture_id=capture_id,
            template="task",
            confidence=0.95,
            fields={"priority": "High"},
            title="Test Task",
            tags=["work", "urgent"],
        )

        assert result is True
        capture = await capture_repo.get_by_id(capture_id)
        assert capture.template_name == "task"
        assert capture.classification_confidence == 0.95
        assert capture.extracted_fields == {"priority": "High"}
        assert capture.suggested_title == "Test Task"
        assert capture.tags == ["work", "urgent"]

    @pytest.mark.asyncio
    async def test_update_notion_result(self, capture_repo: CaptureRepository) -> None:
        """Update Notion result."""
        capture_id = await capture_repo.insert(
            filename="notion.m4a",
            original_path="/inbox/notion.m4a",
        )

        result = await capture_repo.update_notion_result(
            capture_id=capture_id,
            page_id="abc123",
            page_url="https://notion.so/abc123",
        )

        assert result is True
        capture = await capture_repo.get_by_id(capture_id)
        assert capture.notion_page_id == "abc123"
        assert capture.notion_page_url == "https://notion.so/abc123"

    @pytest.mark.asyncio
    async def test_mark_complete(self, capture_repo: CaptureRepository) -> None:
        """Mark capture as complete."""
        capture_id = await capture_repo.insert(
            filename="complete.m4a",
            original_path="/inbox/complete.m4a",
        )

        result = await capture_repo.mark_complete(capture_id)

        assert result is True
        capture = await capture_repo.get_by_id(capture_id)
        assert capture.status == "complete"
        assert capture.completed_at is not None

    @pytest.mark.asyncio
    async def test_reset(self, capture_repo: CaptureRepository) -> None:
        """Reset capture to pending."""
        capture_id = await capture_repo.insert(
            filename="reset.m4a",
            original_path="/inbox/reset.m4a",
        )
        await capture_repo.update_status(capture_id, "failed", error="Test error")
        await capture_repo.increment_retry(capture_id)

        result = await capture_repo.reset(capture_id)

        assert result is True
        capture = await capture_repo.get_by_id(capture_id)
        assert capture.status == "pending"
        assert capture.retry_count == 0
        assert capture.last_error is None

    @pytest.mark.asyncio
    async def test_delete(self, capture_repo: CaptureRepository, failure_repo: FailureLogRepository) -> None:
        """Delete capture and its failure logs."""
        capture_id = await capture_repo.insert(
            filename="delete.m4a",
            original_path="/inbox/delete.m4a",
        )
        await failure_repo.log(capture_id, "test", error_message="Test error")

        result = await capture_repo.delete(capture_id)

        assert result is True
        capture = await capture_repo.get_by_id(capture_id)
        assert capture is None

    @pytest.mark.asyncio
    async def test_get_queue_depth(self, capture_repo: CaptureRepository) -> None:
        """Get queue depth."""
        await capture_repo.insert(filename="q1.m4a", original_path="/inbox/q1.m4a")
        await capture_repo.insert(filename="q2.m4a", original_path="/inbox/q2.m4a")
        id3 = await capture_repo.insert(filename="q3.m4a", original_path="/inbox/q3.m4a")
        await capture_repo.mark_complete(id3)

        depths = await capture_repo.get_queue_depth()

        assert depths["pending"] == 2
        assert depths["complete"] == 1

    @pytest.mark.asyncio
    async def test_get_by_source(self, capture_repo: CaptureRepository) -> None:
        """Get captures by source."""
        await capture_repo.insert(
            filename="watcher1.m4a",
            original_path="/inbox/watcher1.m4a",
            source="watcher",
        )
        await capture_repo.insert(
            filename="http1.m4a",
            original_path="/inbox/http1.m4a",
            source="http",
        )

        watcher_captures = await capture_repo.get_by_source("watcher")
        http_captures = await capture_repo.get_by_source("http")

        assert len(watcher_captures) == 1
        assert len(http_captures) == 1
        assert watcher_captures[0].source == "watcher"
        assert http_captures[0].source == "http"


# ============================================================================
# FailureLogRepository Tests
# ============================================================================


class TestFailureLogRepository:
    """Tests for FailureLogRepository class."""

    @pytest.mark.asyncio
    async def test_log(self, failure_repo: FailureLogRepository, capture_repo: CaptureRepository) -> None:
        """Log a failure."""
        capture_id = await capture_repo.insert(
            filename="fail.m4a",
            original_path="/inbox/fail.m4a",
        )

        log_id = await failure_repo.log(
            capture_id=capture_id,
            stage="transcribing",
            error_type="APIError",
            error_message="Connection failed",
            error_details={"status_code": 500},
        )

        assert log_id > 0

    @pytest.mark.asyncio
    async def test_get_for_capture(self, failure_repo: FailureLogRepository, capture_repo: CaptureRepository) -> None:
        """Get failures for a capture."""
        capture_id = await capture_repo.insert(
            filename="multi_fail.m4a",
            original_path="/inbox/multi_fail.m4a",
        )

        await failure_repo.log(capture_id, "transcribing", error_message="Error 1")
        await failure_repo.log(capture_id, "classifying", error_message="Error 2")

        failures = await failure_repo.get_for_capture(capture_id)

        assert len(failures) == 2
        assert failures[0].error_message == "Error 1"
        assert failures[1].stage == "classifying"

    @pytest.mark.asyncio
    async def test_get_for_capture_empty(self, failure_repo: FailureLogRepository, capture_repo: CaptureRepository) -> None:
        """Get failures for capture with none returns empty list."""
        capture_id = await capture_repo.insert(
            filename="no_fail.m4a",
            original_path="/inbox/no_fail.m4a",
        )

        failures = await failure_repo.get_for_capture(capture_id)

        assert len(failures) == 0

    @pytest.mark.asyncio
    async def test_get_recent(self, failure_repo: FailureLogRepository, capture_repo: CaptureRepository) -> None:
        """Get recent failures."""
        capture_id = await capture_repo.insert(
            filename="recent.m4a",
            original_path="/inbox/recent.m4a",
        )

        for i in range(5):
            await failure_repo.log(capture_id, "test", error_message=f"Error {i}")

        recent = await failure_repo.get_recent(limit=3)

        assert len(recent) == 3

    @pytest.mark.asyncio
    async def test_get_by_stage(self, failure_repo: FailureLogRepository, capture_repo: CaptureRepository) -> None:
        """Get failures by stage."""
        capture_id = await capture_repo.insert(
            filename="stage.m4a",
            original_path="/inbox/stage.m4a",
        )

        await failure_repo.log(capture_id, "transcribing", error_message="T1")
        await failure_repo.log(capture_id, "transcribing", error_message="T2")
        await failure_repo.log(capture_id, "posting", error_message="P1")

        transcribing = await failure_repo.get_by_stage("transcribing")
        posting = await failure_repo.get_by_stage("posting")

        assert len(transcribing) == 2
        assert len(posting) == 1

    @pytest.mark.asyncio
    async def test_delete_for_capture(self, failure_repo: FailureLogRepository, capture_repo: CaptureRepository) -> None:
        """Delete failures for a capture."""
        capture_id = await capture_repo.insert(
            filename="del_fail.m4a",
            original_path="/inbox/del_fail.m4a",
        )

        await failure_repo.log(capture_id, "test", error_message="E1")
        await failure_repo.log(capture_id, "test", error_message="E2")

        deleted = await failure_repo.delete_for_capture(capture_id)

        assert deleted == 2
        failures = await failure_repo.get_for_capture(capture_id)
        assert len(failures) == 0


# ============================================================================
# StatisticsRepository Tests
# ============================================================================


class TestStatisticsRepository:
    """Tests for StatisticsRepository class."""

    @pytest.mark.asyncio
    async def test_get_not_found(self, stats_repo: StatisticsRepository) -> None:
        """Get stats for date with no data returns None."""
        stats = await stats_repo.get("2026-01-01")
        assert stats is None

    @pytest.mark.asyncio
    async def test_update_create(self, stats_repo: StatisticsRepository) -> None:
        """Create new stats via update."""
        result = await stats_repo.update(
            date="2026-01-20",
            captures_received=10,
            captures_completed=8,
            captures_failed=2,
        )

        assert result is True
        stats = await stats_repo.get("2026-01-20")
        assert stats is not None
        assert stats.captures_received == 10
        assert stats.captures_completed == 8
        assert stats.captures_failed == 2

    @pytest.mark.asyncio
    async def test_update_partial(self, stats_repo: StatisticsRepository) -> None:
        """Partial update preserves existing values."""
        await stats_repo.update(
            date="2026-01-21",
            captures_received=5,
            captures_completed=4,
        )

        await stats_repo.update(
            date="2026-01-21",
            captures_failed=1,
        )

        stats = await stats_repo.get("2026-01-21")
        assert stats.captures_received == 5  # Preserved
        assert stats.captures_completed == 4  # Preserved
        assert stats.captures_failed == 1  # Updated

    @pytest.mark.asyncio
    async def test_increment(self, stats_repo: StatisticsRepository) -> None:
        """Increment stat atomically."""
        date = "2026-01-22"

        value = await stats_repo.increment(date, "captures_received")
        assert value == 1

        value = await stats_repo.increment(date, "captures_received")
        assert value == 2

        value = await stats_repo.increment(date, "captures_completed", amount=5)
        assert value == 5

    @pytest.mark.asyncio
    async def test_increment_invalid_field(self, stats_repo: StatisticsRepository) -> None:
        """Increment invalid field raises ValueError."""
        with pytest.raises(ValueError, match="Invalid field"):
            await stats_repo.increment("2026-01-23", "invalid_field")

    @pytest.mark.asyncio
    async def test_get_for_date_range(self, stats_repo: StatisticsRepository) -> None:
        """Get stats for date range."""
        dates = ["2026-01-18", "2026-01-19", "2026-01-20", "2026-01-21"]

        for i, date in enumerate(dates):
            await stats_repo.update(date=date, captures_received=i + 1)

        stats = await stats_repo.get_for_date_range("2026-01-19", "2026-01-20")

        assert len(stats) == 2
        assert stats[0].date == "2026-01-19"
        assert stats[0].captures_received == 2
        assert stats[1].date == "2026-01-20"
        assert stats[1].captures_received == 3

    @pytest.mark.asyncio
    async def test_add_audio_duration(self, stats_repo: StatisticsRepository) -> None:
        """Add audio duration to daily total."""
        date = "2026-01-24"

        total = await stats_repo.add_audio_duration(date, 30.5)
        assert total == 30.5

        total = await stats_repo.add_audio_duration(date, 20.0)
        assert total == 50.5

    @pytest.mark.asyncio
    async def test_update_template_breakdown(self, stats_repo: StatisticsRepository) -> None:
        """Update template breakdown."""
        date = "2026-01-25"

        breakdown = await stats_repo.update_template_breakdown(date, "task")
        assert breakdown == {"task": 1}

        breakdown = await stats_repo.update_template_breakdown(date, "task")
        assert breakdown == {"task": 2}

        breakdown = await stats_repo.update_template_breakdown(date, "journal")
        assert breakdown == {"task": 2, "journal": 1}


# ============================================================================
# BaseRepository Tests
# ============================================================================


class TestBaseRepository:
    """Tests for BaseRepository class."""

    @pytest.mark.asyncio
    async def test_get_connection(self, pool: ConnectionPool) -> None:
        """BaseRepository can acquire connections."""
        repo = BaseRepository(pool)

        async with repo._get_connection() as conn:
            cursor = await conn.execute("SELECT 1")
            result = await cursor.fetchone()
            assert result[0] == 1
