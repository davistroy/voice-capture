"""Query layer for queue status data.

This module separates data fetching from presentation concerns,
making the queue status functionality more testable.

Classes:
    FailureInfo: Information about a failed capture
    HttpStats: HTTP upload statistics
    InProgressInfo: Information about an in-progress capture
    PendingInfo: Information about a pending capture
    QueueStatusData: Complete queue status data transfer object
    QueueStatusQuery: Query layer for fetching queue status data
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional, Protocol

from src.db.models import CaptureRow


class DatabaseProtocol(Protocol):
    """Protocol for database operations needed by queue status queries."""

    async def get_queue_depth(self) -> dict[str, int]:
        """Get count of captures by status."""
        ...

    async def get_captures_by_status(self, status: str) -> list[CaptureRow]:
        """Get all captures with a specific status."""
        ...

    async def get_source_stats(self, hours: int = 24) -> dict[str, dict[str, int]]:
        """Get capture statistics grouped by source."""
        ...

    async def get_recent_http_uploads(self, limit: int = 10) -> list[CaptureRow]:
        """Get recent HTTP uploads."""
        ...


@dataclass(frozen=True)
class FailureInfo:
    """Information about a failed capture."""

    capture_id: int
    filename: str
    error_message: str
    stage: Optional[str]
    retry_count: int
    last_attempt_at: Optional[datetime] = None
    captured_at: Optional[datetime] = None

    @classmethod
    def from_capture_row(cls, row: CaptureRow) -> "FailureInfo":
        """Create FailureInfo from a CaptureRow."""
        return cls(
            capture_id=row.id or 0,
            filename=row.filename,
            error_message=row.last_error or "Unknown error",
            stage=row.status,  # Current status indicates the failed stage
            retry_count=row.retry_count,
            last_attempt_at=row.last_attempt_at,
            captured_at=row.captured_at,
        )


@dataclass(frozen=True)
class PendingInfo:
    """Information about a pending capture."""

    capture_id: int
    filename: str
    device: str
    created_at: Optional[datetime] = None

    @classmethod
    def from_capture_row(cls, row: CaptureRow) -> "PendingInfo":
        """Create PendingInfo from a CaptureRow."""
        return cls(
            capture_id=row.id or 0,
            filename=row.filename,
            device=row.device or "unknown",
            created_at=row.created_at,
        )


@dataclass(frozen=True)
class InProgressInfo:
    """Information about an in-progress capture."""

    capture_id: int
    filename: str
    stage: str
    started_at: Optional[datetime] = None

    @classmethod
    def from_capture_row(cls, row: CaptureRow) -> "InProgressInfo":
        """Create InProgressInfo from a CaptureRow."""
        return cls(
            capture_id=row.id or 0,
            filename=row.filename,
            stage=row.status,
            started_at=row.last_attempt_at or row.updated_at,
        )


@dataclass(frozen=True)
class RecentUploadInfo:
    """Information about a recent HTTP upload."""

    capture_id: int
    filename: str
    status: str
    template_name: Optional[str]
    created_at: Optional[datetime] = None

    @classmethod
    def from_capture_row(cls, row: CaptureRow) -> "RecentUploadInfo":
        """Create RecentUploadInfo from a CaptureRow."""
        return cls(
            capture_id=row.id or 0,
            filename=row.filename,
            status=row.status,
            template_name=row.template_name,
            created_at=row.created_at,
        )


@dataclass(frozen=True)
class SourceStats:
    """Statistics for a single upload source."""

    total: int
    complete: int
    failed: int
    pending: int  # Includes all non-terminal states

    @classmethod
    def from_stats_dict(cls, stats: dict[str, int]) -> "SourceStats":
        """Create SourceStats from a status counts dictionary."""
        complete = stats.get("complete", 0)
        failed = stats.get("failed", 0)
        # Pending includes all non-terminal processing states
        pending = (
            stats.get("pending", 0)
            + stats.get("transcribing", 0)
            + stats.get("classifying", 0)
            + stats.get("posting", 0)
        )
        total = sum(stats.values())

        return cls(
            total=total,
            complete=complete,
            failed=failed,
            pending=pending,
        )


@dataclass(frozen=True)
class HttpStats:
    """HTTP upload statistics."""

    http_source: SourceStats
    watcher_source: SourceStats
    recent_uploads: List[RecentUploadInfo] = field(default_factory=list)


@dataclass(frozen=True)
class QueueCounts:
    """Counts of captures in various states."""

    pending: int
    transcribing: int
    classifying: int
    posting: int
    failed: int
    complete: int

    @property
    def in_progress(self) -> int:
        """Total number of captures currently being processed."""
        return self.transcribing + self.classifying + self.posting

    @property
    def total(self) -> int:
        """Total number of captures across all states."""
        return (
            self.pending
            + self.transcribing
            + self.classifying
            + self.posting
            + self.failed
            + self.complete
        )


@dataclass
class QueueStatusData:
    """Complete data transfer object for queue status.

    This contains all the data needed to display queue status,
    without any presentation logic.
    """

    counts: QueueCounts
    pending_items: List[PendingInfo] = field(default_factory=list)
    in_progress_items: List[InProgressInfo] = field(default_factory=list)
    failed_items: List[FailureInfo] = field(default_factory=list)
    http_stats: Optional[HttpStats] = None


class QueueStatusQuery:
    """Query layer for queue status data.

    Separates data fetching from presentation, making the code
    more testable and maintainable.

    Usage:
        query = QueueStatusQuery(db)
        data = await query.get_status(include_http=True)
        # Pass data to presenter for display
    """

    def __init__(self, db: DatabaseProtocol):
        """Initialize the query layer.

        Args:
            db: Database instance implementing DatabaseProtocol
        """
        self._db = db

    async def get_status(self, include_http: bool = False) -> QueueStatusData:
        """Get complete queue status data.

        Args:
            include_http: Whether to include HTTP upload statistics

        Returns:
            QueueStatusData containing all queue information
        """
        # Fetch counts by status
        queue_depth = await self._db.get_queue_depth()

        # Fetch capture lists for each status
        pending_rows = await self._db.get_captures_by_status("pending")
        transcribing_rows = await self._db.get_captures_by_status("transcribing")
        classifying_rows = await self._db.get_captures_by_status("classifying")
        posting_rows = await self._db.get_captures_by_status("posting")
        failed_rows = await self._db.get_captures_by_status("failed")
        complete_rows = await self._db.get_captures_by_status("complete")

        # Build counts
        counts = QueueCounts(
            pending=len(pending_rows),
            transcribing=len(transcribing_rows),
            classifying=len(classifying_rows),
            posting=len(posting_rows),
            failed=len(failed_rows),
            complete=len(complete_rows),
        )

        # Convert to DTOs
        pending_items = [PendingInfo.from_capture_row(row) for row in pending_rows]

        in_progress_items = []
        for row in transcribing_rows + classifying_rows + posting_rows:
            in_progress_items.append(InProgressInfo.from_capture_row(row))

        failed_items = [FailureInfo.from_capture_row(row) for row in failed_rows]

        # Optionally fetch HTTP stats
        http_stats = None
        if include_http:
            http_stats = await self._get_http_stats()

        return QueueStatusData(
            counts=counts,
            pending_items=pending_items,
            in_progress_items=in_progress_items,
            failed_items=failed_items,
            http_stats=http_stats,
        )

    async def get_http_stats_only(self) -> HttpStats:
        """Get only HTTP upload statistics.

        Returns:
            HttpStats containing HTTP-specific information
        """
        return await self._get_http_stats()

    async def _get_http_stats(self) -> HttpStats:
        """Internal method to fetch HTTP statistics."""
        source_stats = await self._db.get_source_stats(hours=24)
        recent_uploads = await self._db.get_recent_http_uploads(limit=10)

        http_source = SourceStats.from_stats_dict(source_stats.get("http", {}))
        watcher_source = SourceStats.from_stats_dict(source_stats.get("watcher", {}))

        recent_info = [RecentUploadInfo.from_capture_row(row) for row in recent_uploads]

        return HttpStats(
            http_source=http_source,
            watcher_source=watcher_source,
            recent_uploads=recent_info,
        )
