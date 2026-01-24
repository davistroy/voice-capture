"""Tests for queue status query layer.

Tests the data classes and QueueStatusQuery without Rich dependency.
"""

from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cli.queue_status_query import (
    FailureInfo,
    HttpStats,
    InProgressInfo,
    PendingInfo,
    QueueCounts,
    QueueStatusData,
    QueueStatusQuery,
    RecentUploadInfo,
    SourceStats,
)
from src.db.models import CaptureRow


# ===========================================================================
# Data Class Tests
# ===========================================================================


class TestQueueCounts:
    """Tests for QueueCounts data class."""

    def test_in_progress_calculation(self):
        """Test that in_progress is sum of processing states."""
        counts = QueueCounts(
            pending=5,
            transcribing=2,
            classifying=1,
            posting=3,
            failed=2,
            complete=10,
        )

        assert counts.in_progress == 6  # 2 + 1 + 3

    def test_total_calculation(self):
        """Test that total is sum of all states."""
        counts = QueueCounts(
            pending=5,
            transcribing=2,
            classifying=1,
            posting=3,
            failed=2,
            complete=10,
        )

        assert counts.total == 23  # 5 + 2 + 1 + 3 + 2 + 10

    def test_zero_counts(self):
        """Test with all zero counts."""
        counts = QueueCounts(
            pending=0,
            transcribing=0,
            classifying=0,
            posting=0,
            failed=0,
            complete=0,
        )

        assert counts.in_progress == 0
        assert counts.total == 0


class TestFailureInfo:
    """Tests for FailureInfo data class."""

    def test_from_capture_row(self):
        """Test creating FailureInfo from CaptureRow."""
        row = CaptureRow(
            id=42,
            filename="test.m4a",
            original_path="/path/test.m4a",
            status="failed",
            retry_count=3,
            last_error="Transcription timeout",
            last_attempt_at=datetime(2026, 1, 20, 10, 0, 0),
            captured_at=datetime(2026, 1, 20, 9, 0, 0),
        )

        info = FailureInfo.from_capture_row(row)

        assert info.capture_id == 42
        assert info.filename == "test.m4a"
        assert info.error_message == "Transcription timeout"
        assert info.stage == "failed"
        assert info.retry_count == 3
        assert info.last_attempt_at == datetime(2026, 1, 20, 10, 0, 0)
        assert info.captured_at == datetime(2026, 1, 20, 9, 0, 0)

    def test_from_capture_row_missing_error(self):
        """Test creating FailureInfo when last_error is None."""
        row = CaptureRow(
            id=42,
            filename="test.m4a",
            original_path="/path/test.m4a",
            status="failed",
            retry_count=1,
            last_error=None,
        )

        info = FailureInfo.from_capture_row(row)

        assert info.error_message == "Unknown error"

    def test_from_capture_row_missing_id(self):
        """Test creating FailureInfo when id is None."""
        row = CaptureRow(
            id=None,
            filename="test.m4a",
            original_path="/path/test.m4a",
            status="failed",
            retry_count=0,
        )

        info = FailureInfo.from_capture_row(row)

        assert info.capture_id == 0

    def test_frozen_dataclass(self):
        """Test that FailureInfo is immutable."""
        info = FailureInfo(
            capture_id=1,
            filename="test.m4a",
            error_message="Error",
            stage="failed",
            retry_count=0,
        )

        with pytest.raises(AttributeError):
            info.capture_id = 2  # type: ignore


class TestPendingInfo:
    """Tests for PendingInfo data class."""

    def test_from_capture_row(self):
        """Test creating PendingInfo from CaptureRow."""
        row = CaptureRow(
            id=10,
            filename="pending.m4a",
            original_path="/path/pending.m4a",
            device="watch",
            created_at=datetime(2026, 1, 20, 8, 0, 0),
        )

        info = PendingInfo.from_capture_row(row)

        assert info.capture_id == 10
        assert info.filename == "pending.m4a"
        assert info.device == "watch"
        assert info.created_at == datetime(2026, 1, 20, 8, 0, 0)

    def test_from_capture_row_missing_device(self):
        """Test creating PendingInfo when device is None."""
        row = CaptureRow(
            id=10,
            filename="pending.m4a",
            original_path="/path/pending.m4a",
            device=None,
        )

        info = PendingInfo.from_capture_row(row)

        assert info.device == "unknown"


class TestInProgressInfo:
    """Tests for InProgressInfo data class."""

    def test_from_capture_row_transcribing(self):
        """Test creating InProgressInfo from transcribing capture."""
        row = CaptureRow(
            id=15,
            filename="transcribing.m4a",
            original_path="/path/transcribing.m4a",
            status="transcribing",
            last_attempt_at=datetime(2026, 1, 20, 10, 30, 0),
        )

        info = InProgressInfo.from_capture_row(row)

        assert info.capture_id == 15
        assert info.filename == "transcribing.m4a"
        assert info.stage == "transcribing"
        assert info.started_at == datetime(2026, 1, 20, 10, 30, 0)

    def test_from_capture_row_uses_updated_at_fallback(self):
        """Test that updated_at is used when last_attempt_at is None."""
        row = CaptureRow(
            id=15,
            filename="classifying.m4a",
            original_path="/path/classifying.m4a",
            status="classifying",
            last_attempt_at=None,
            updated_at=datetime(2026, 1, 20, 10, 45, 0),
        )

        info = InProgressInfo.from_capture_row(row)

        assert info.started_at == datetime(2026, 1, 20, 10, 45, 0)


class TestRecentUploadInfo:
    """Tests for RecentUploadInfo data class."""

    def test_from_capture_row(self):
        """Test creating RecentUploadInfo from CaptureRow."""
        row = CaptureRow(
            id=20,
            filename="recent.m4a",
            original_path="/path/recent.m4a",
            status="complete",
            template_name="journal",
            created_at=datetime(2026, 1, 20, 11, 0, 0),
        )

        info = RecentUploadInfo.from_capture_row(row)

        assert info.capture_id == 20
        assert info.filename == "recent.m4a"
        assert info.status == "complete"
        assert info.template_name == "journal"
        assert info.created_at == datetime(2026, 1, 20, 11, 0, 0)

    def test_from_capture_row_no_template(self):
        """Test creating RecentUploadInfo when template_name is None."""
        row = CaptureRow(
            id=20,
            filename="recent.m4a",
            original_path="/path/recent.m4a",
            status="pending",
            template_name=None,
        )

        info = RecentUploadInfo.from_capture_row(row)

        assert info.template_name is None


class TestSourceStats:
    """Tests for SourceStats data class."""

    def test_from_stats_dict(self):
        """Test creating SourceStats from status counts dictionary."""
        stats_dict = {
            "pending": 5,
            "transcribing": 2,
            "classifying": 1,
            "posting": 1,
            "failed": 3,
            "complete": 20,
        }

        stats = SourceStats.from_stats_dict(stats_dict)

        assert stats.total == 32
        assert stats.complete == 20
        assert stats.failed == 3
        assert stats.pending == 9  # 5 + 2 + 1 + 1

    def test_from_stats_dict_empty(self):
        """Test creating SourceStats from empty dictionary."""
        stats = SourceStats.from_stats_dict({})

        assert stats.total == 0
        assert stats.complete == 0
        assert stats.failed == 0
        assert stats.pending == 0


class TestHttpStats:
    """Tests for HttpStats data class."""

    def test_creation(self):
        """Test creating HttpStats."""
        http_source = SourceStats(total=10, complete=8, failed=1, pending=1)
        watcher_source = SourceStats(total=20, complete=18, failed=1, pending=1)

        stats = HttpStats(
            http_source=http_source,
            watcher_source=watcher_source,
            recent_uploads=[],
        )

        assert stats.http_source.total == 10
        assert stats.watcher_source.total == 20
        assert len(stats.recent_uploads) == 0


class TestQueueStatusData:
    """Tests for QueueStatusData data class."""

    def test_creation(self):
        """Test creating QueueStatusData."""
        counts = QueueCounts(
            pending=2,
            transcribing=1,
            classifying=0,
            posting=0,
            failed=1,
            complete=5,
        )

        data = QueueStatusData(
            counts=counts,
            pending_items=[],
            in_progress_items=[],
            failed_items=[],
            http_stats=None,
        )

        assert data.counts.pending == 2
        assert data.counts.total == 9
        assert data.http_stats is None


# ===========================================================================
# Query Layer Tests
# ===========================================================================


class TestQueueStatusQuery:
    """Tests for QueueStatusQuery class."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database."""
        db = AsyncMock()

        # Default return values
        db.get_queue_depth.return_value = {
            "pending": 2,
            "transcribing": 1,
            "classifying": 0,
            "posting": 0,
            "failed": 1,
            "complete": 5,
        }

        db.get_captures_by_status.side_effect = self._get_captures_by_status
        db.get_source_stats.return_value = {
            "http": {"complete": 3, "failed": 1, "pending": 1},
            "watcher": {"complete": 5, "failed": 0, "pending": 0},
        }
        db.get_recent_http_uploads.return_value = []

        return db

    def _get_captures_by_status(self, status: str) -> list[CaptureRow]:
        """Return mock captures based on status."""
        captures = {
            "pending": [
                CaptureRow(
                    id=1,
                    filename="pending1.m4a",
                    original_path="/path/pending1.m4a",
                    device="watch",
                    status="pending",
                ),
                CaptureRow(
                    id=2,
                    filename="pending2.m4a",
                    original_path="/path/pending2.m4a",
                    device="phone",
                    status="pending",
                ),
            ],
            "transcribing": [
                CaptureRow(
                    id=3,
                    filename="transcribing1.m4a",
                    original_path="/path/transcribing1.m4a",
                    status="transcribing",
                ),
            ],
            "classifying": [],
            "posting": [],
            "failed": [
                CaptureRow(
                    id=4,
                    filename="failed1.m4a",
                    original_path="/path/failed1.m4a",
                    status="failed",
                    last_error="Timeout error",
                    retry_count=2,
                ),
            ],
            "complete": [
                CaptureRow(
                    id=5,
                    filename=f"complete{i}.m4a",
                    original_path=f"/path/complete{i}.m4a",
                    status="complete",
                )
                for i in range(5)
            ],
        }
        return captures.get(status, [])

    @pytest.mark.asyncio
    async def test_get_status_counts(self, mock_db):
        """Test that get_status returns correct counts."""
        query = QueueStatusQuery(mock_db)
        data = await query.get_status()

        assert data.counts.pending == 2
        assert data.counts.transcribing == 1
        assert data.counts.classifying == 0
        assert data.counts.posting == 0
        assert data.counts.failed == 1
        assert data.counts.complete == 5
        assert data.counts.in_progress == 1
        assert data.counts.total == 9

    @pytest.mark.asyncio
    async def test_get_status_pending_items(self, mock_db):
        """Test that get_status returns pending items."""
        query = QueueStatusQuery(mock_db)
        data = await query.get_status()

        assert len(data.pending_items) == 2
        assert data.pending_items[0].filename == "pending1.m4a"
        assert data.pending_items[0].device == "watch"
        assert data.pending_items[1].filename == "pending2.m4a"
        assert data.pending_items[1].device == "phone"

    @pytest.mark.asyncio
    async def test_get_status_in_progress_items(self, mock_db):
        """Test that get_status returns in-progress items."""
        query = QueueStatusQuery(mock_db)
        data = await query.get_status()

        assert len(data.in_progress_items) == 1
        assert data.in_progress_items[0].filename == "transcribing1.m4a"
        assert data.in_progress_items[0].stage == "transcribing"

    @pytest.mark.asyncio
    async def test_get_status_failed_items(self, mock_db):
        """Test that get_status returns failed items."""
        query = QueueStatusQuery(mock_db)
        data = await query.get_status()

        assert len(data.failed_items) == 1
        assert data.failed_items[0].filename == "failed1.m4a"
        assert data.failed_items[0].error_message == "Timeout error"
        assert data.failed_items[0].retry_count == 2

    @pytest.mark.asyncio
    async def test_get_status_without_http(self, mock_db):
        """Test that http_stats is None when include_http=False."""
        query = QueueStatusQuery(mock_db)
        data = await query.get_status(include_http=False)

        assert data.http_stats is None
        mock_db.get_source_stats.assert_not_called()
        mock_db.get_recent_http_uploads.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_status_with_http(self, mock_db):
        """Test that http_stats is populated when include_http=True."""
        query = QueueStatusQuery(mock_db)
        data = await query.get_status(include_http=True)

        assert data.http_stats is not None
        assert data.http_stats.http_source.total == 5  # 3 + 1 + 1
        assert data.http_stats.watcher_source.total == 5  # 5 + 0 + 0
        mock_db.get_source_stats.assert_called_once_with(hours=24)
        mock_db.get_recent_http_uploads.assert_called_once_with(limit=10)

    @pytest.mark.asyncio
    async def test_get_http_stats_only(self, mock_db):
        """Test get_http_stats_only method."""
        # Add some recent uploads
        mock_db.get_recent_http_uploads.return_value = [
            CaptureRow(
                id=10,
                filename="http1.m4a",
                original_path="/path/http1.m4a",
                status="complete",
                template_name="journal",
                source="http",
            ),
        ]

        query = QueueStatusQuery(mock_db)
        http_stats = await query.get_http_stats_only()

        assert http_stats.http_source.complete == 3
        assert http_stats.http_source.failed == 1
        assert http_stats.watcher_source.complete == 5
        assert len(http_stats.recent_uploads) == 1
        assert http_stats.recent_uploads[0].filename == "http1.m4a"

    @pytest.mark.asyncio
    async def test_empty_database(self):
        """Test with an empty database."""
        # Create a fresh mock with empty data
        mock_db = AsyncMock()
        mock_db.get_queue_depth.return_value = {}
        mock_db.get_captures_by_status.return_value = []
        mock_db.get_source_stats.return_value = {}
        mock_db.get_recent_http_uploads.return_value = []

        query = QueueStatusQuery(mock_db)
        data = await query.get_status()

        assert data.counts.pending == 0
        assert data.counts.total == 0
        assert len(data.pending_items) == 0
        assert len(data.in_progress_items) == 0
        assert len(data.failed_items) == 0


class TestQueueStatusQueryIntegration:
    """Integration tests with real database."""

    @pytest.fixture
    async def db(self, temp_dir):
        """Create a real test database."""
        from src.db.database import Database

        db_path = temp_dir / "test_query.db"
        db = Database(db_path)
        await db.initialize()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_with_real_database_empty(self, db):
        """Test query with real empty database."""
        query = QueueStatusQuery(db)
        data = await query.get_status()

        assert data.counts.total == 0
        assert len(data.pending_items) == 0
        assert len(data.failed_items) == 0

    @pytest.mark.asyncio
    async def test_with_real_database_populated(self, db):
        """Test query with populated database."""
        # Insert test data
        await db.insert_capture(
            filename="test1.m4a",
            original_path="/path/test1.m4a",
            device="watch",
        )

        failed_id = await db.insert_capture(
            filename="test2.m4a",
            original_path="/path/test2.m4a",
            device="phone",
        )
        await db.update_status(failed_id, "failed", error="Test error")

        query = QueueStatusQuery(db)
        data = await query.get_status()

        assert data.counts.pending == 1
        assert data.counts.failed == 1
        assert data.counts.total == 2
        assert len(data.pending_items) == 1
        assert len(data.failed_items) == 1
        assert data.failed_items[0].error_message == "Test error"

    @pytest.mark.asyncio
    async def test_http_stats_with_real_database(self, db):
        """Test HTTP stats with populated database."""
        # Insert HTTP uploads
        await db.insert_capture(
            filename="http1.m4a",
            original_path="/path/http1.m4a",
            source="http",
        )

        # Insert watcher uploads
        await db.insert_capture(
            filename="watcher1.m4a",
            original_path="/path/watcher1.m4a",
            source="watcher",
        )

        query = QueueStatusQuery(db)
        http_stats = await query.get_http_stats_only()

        assert http_stats.http_source.total == 1
        assert http_stats.watcher_source.total == 1
        assert len(http_stats.recent_uploads) == 1
