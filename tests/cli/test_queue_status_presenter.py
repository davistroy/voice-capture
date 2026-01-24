"""Tests for queue status presenter layer.

Tests the QueueStatusPresenter with mocked Rich Console.
"""

from datetime import datetime
from io import StringIO
from unittest.mock import MagicMock, call, patch

import pytest
from rich.console import Console
from rich.table import Table

from src.cli.queue_status_presenter import QueueStatusPresenter, _format_datetime
from src.cli.queue_status_query import (
    FailureInfo,
    HttpStats,
    InProgressInfo,
    PendingInfo,
    QueueCounts,
    QueueStatusData,
    RecentUploadInfo,
    SourceStats,
)


# ===========================================================================
# Helper Function Tests
# ===========================================================================


class TestFormatDatetime:
    """Tests for _format_datetime helper."""

    def test_format_none(self):
        """Test formatting None returns dash."""
        assert _format_datetime(None) == "-"

    def test_format_datetime(self):
        """Test formatting a datetime object."""
        dt = datetime(2026, 1, 20, 10, 30, 45)
        assert _format_datetime(dt) == "2026-01-20 10:30:45"

    def test_format_string(self):
        """Test formatting a datetime string (truncated to 19 chars)."""
        dt_str = "2026-01-20T10:30:45.123456"
        # Truncates to 19 characters (date and time)
        assert _format_datetime(dt_str) == "2026-01-20T10:30:45"


# ===========================================================================
# Presenter Tests
# ===========================================================================


class TestQueueStatusPresenter:
    """Tests for QueueStatusPresenter class."""

    @pytest.fixture
    def mock_console(self):
        """Create a mock console that captures output."""
        console = MagicMock(spec=Console)
        return console

    @pytest.fixture
    def string_console(self):
        """Create a real console that writes to a string."""
        output = StringIO()
        # Use no_color=True to avoid ANSI escape codes in tests
        console = Console(file=output, force_terminal=False, width=120, no_color=True)
        console._output = output  # Store reference for testing
        return console

    @pytest.fixture
    def sample_counts(self):
        """Create sample queue counts."""
        return QueueCounts(
            pending=3,
            transcribing=1,
            classifying=1,
            posting=0,
            failed=2,
            complete=10,
        )

    @pytest.fixture
    def sample_data(self, sample_counts):
        """Create sample queue status data."""
        return QueueStatusData(
            counts=sample_counts,
            pending_items=[
                PendingInfo(
                    capture_id=1,
                    filename="pending1.m4a",
                    device="watch",
                    created_at=datetime(2026, 1, 20, 8, 0, 0),
                ),
                PendingInfo(
                    capture_id=2,
                    filename="pending2.m4a",
                    device="phone",
                    created_at=datetime(2026, 1, 20, 8, 30, 0),
                ),
            ],
            in_progress_items=[
                InProgressInfo(
                    capture_id=3,
                    filename="transcribing1.m4a",
                    stage="transcribing",
                    started_at=datetime(2026, 1, 20, 9, 0, 0),
                ),
                InProgressInfo(
                    capture_id=4,
                    filename="classifying1.m4a",
                    stage="classifying",
                    started_at=datetime(2026, 1, 20, 9, 5, 0),
                ),
            ],
            failed_items=[
                FailureInfo(
                    capture_id=5,
                    filename="failed1.m4a",
                    error_message="Transcription timeout",
                    stage="transcribing",
                    retry_count=3,
                    last_attempt_at=datetime(2026, 1, 20, 10, 0, 0),
                    captured_at=datetime(2026, 1, 20, 7, 0, 0),
                ),
            ],
        )

    @pytest.fixture
    def sample_http_stats(self):
        """Create sample HTTP stats."""
        return HttpStats(
            http_source=SourceStats(total=15, complete=12, failed=2, pending=1),
            watcher_source=SourceStats(total=30, complete=28, failed=1, pending=1),
            recent_uploads=[
                RecentUploadInfo(
                    capture_id=100,
                    filename="http_upload.m4a",
                    status="complete",
                    template_name="journal",
                    created_at=datetime(2026, 1, 20, 11, 0, 0),
                ),
            ],
        )

    def test_display_calls_all_sections(self, mock_console, sample_data):
        """Test that display calls all required print methods."""
        presenter = QueueStatusPresenter(mock_console)

        presenter.display(
            sample_data,
            verbose=False,
            show_http_status=True,
            http_enabled=True,
            http_host="0.0.0.0",
            http_port=8080,
            http_auth_enabled=True,
        )

        # Verify console.print was called multiple times
        assert mock_console.print.call_count > 0

    def test_display_failed_only(self, mock_console, sample_data):
        """Test display_failed_only method."""
        presenter = QueueStatusPresenter(mock_console)

        presenter.display_failed_only(sample_data, verbose=False)

        # Should have printed table and hints
        assert mock_console.print.call_count >= 3

    def test_display_pending_only(self, mock_console, sample_data):
        """Test display_pending_only method."""
        presenter = QueueStatusPresenter(mock_console)

        presenter.display_pending_only(sample_data)

        # Should have printed table and timestamp
        assert mock_console.print.call_count >= 2

    def test_display_in_progress_only(self, mock_console, sample_data):
        """Test display_in_progress_only method."""
        presenter = QueueStatusPresenter(mock_console)

        presenter.display_in_progress_only(sample_data)

        # Should have printed table and timestamp
        assert mock_console.print.call_count >= 2

    def test_display_http_only(self, mock_console, sample_http_stats):
        """Test display_http_only method."""
        presenter = QueueStatusPresenter(mock_console)

        presenter.display_http_only(
            sample_http_stats,
            verbose=False,
            http_enabled=True,
            http_host="localhost",
            http_port=8080,
            http_auth_enabled=False,
        )

        # Should have printed status, table, and timestamp
        assert mock_console.print.call_count >= 3

    def test_empty_failed_items(self, mock_console):
        """Test display with no failed items."""
        data = QueueStatusData(
            counts=QueueCounts(0, 0, 0, 0, 0, 0),
            pending_items=[],
            in_progress_items=[],
            failed_items=[],
        )

        presenter = QueueStatusPresenter(mock_console)
        presenter.display_failed_only(data)

        # Should print "No failed captures" message
        calls = mock_console.print.call_args_list
        output_texts = [str(call) for call in calls]
        assert any("No failed captures" in text for text in output_texts)

    def test_empty_pending_items(self, mock_console):
        """Test display with no pending items."""
        data = QueueStatusData(
            counts=QueueCounts(0, 0, 0, 0, 0, 0),
            pending_items=[],
            in_progress_items=[],
            failed_items=[],
        )

        presenter = QueueStatusPresenter(mock_console)
        presenter.display_pending_only(data)

        calls = mock_console.print.call_args_list
        output_texts = [str(call) for call in calls]
        assert any("No pending captures" in text for text in output_texts)

    def test_empty_in_progress_items(self, mock_console):
        """Test display with no in-progress items."""
        data = QueueStatusData(
            counts=QueueCounts(0, 0, 0, 0, 0, 0),
            pending_items=[],
            in_progress_items=[],
            failed_items=[],
        )

        presenter = QueueStatusPresenter(mock_console)
        presenter.display_in_progress_only(data)

        calls = mock_console.print.call_args_list
        output_texts = [str(call) for call in calls]
        assert any("No captures currently processing" in text for text in output_texts)

    def test_verbose_shows_extra_columns(self, string_console, sample_data):
        """Test that verbose mode shows additional columns."""
        presenter = QueueStatusPresenter(string_console)

        presenter.display_failed_only(sample_data, verbose=True)

        output = string_console._output.getvalue()
        # Verbose mode should show timestamps
        assert "2026-01-20" in output

    def test_error_message_truncation(self, string_console):
        """Test that long error messages are truncated."""
        long_error = "A" * 100  # Error longer than max_error_len
        data = QueueStatusData(
            counts=QueueCounts(0, 0, 0, 0, 1, 0),
            pending_items=[],
            in_progress_items=[],
            failed_items=[
                FailureInfo(
                    capture_id=1,
                    filename="test.m4a",
                    error_message=long_error,
                    stage="failed",
                    retry_count=1,
                ),
            ],
        )

        presenter = QueueStatusPresenter(string_console)
        presenter.display_failed_only(data, verbose=False)

        output = string_console._output.getvalue()
        # Error should be truncated with ellipsis
        assert "..." in output
        # Full error should not be present
        assert long_error not in output

    def test_http_server_enabled_status(self, string_console, sample_http_stats):
        """Test HTTP server enabled status display."""
        presenter = QueueStatusPresenter(string_console)

        presenter.display_http_only(
            sample_http_stats,
            http_enabled=True,
            http_host="0.0.0.0",
            http_port=8080,
            http_auth_enabled=True,
        )

        output = string_console._output.getvalue()
        assert "HTTP Server" in output
        assert "0.0.0.0:8080" in output

    def test_http_server_disabled_status(self, string_console, sample_http_stats):
        """Test HTTP server disabled status display."""
        presenter = QueueStatusPresenter(string_console)

        presenter.display_http_only(
            sample_http_stats,
            http_enabled=False,
            http_host="",
            http_port=0,
            http_auth_enabled=False,
        )

        output = string_console._output.getvalue()
        assert "HTTP Server" in output
        assert "Disabled" in output

    def test_empty_http_uploads(self, string_console):
        """Test display with no HTTP uploads."""
        http_stats = HttpStats(
            http_source=SourceStats(total=0, complete=0, failed=0, pending=0),
            watcher_source=SourceStats(total=0, complete=0, failed=0, pending=0),
            recent_uploads=[],
        )

        presenter = QueueStatusPresenter(string_console)
        presenter.display_http_only(
            http_stats,
            http_enabled=True,
            http_host="localhost",
            http_port=8080,
            http_auth_enabled=False,
        )

        output = string_console._output.getvalue()
        assert "No HTTP uploads in the last 24 hours" in output

    def test_filename_truncation(self, string_console):
        """Test that long filenames are truncated in recent uploads."""
        long_filename = "a" * 50 + ".m4a"
        http_stats = HttpStats(
            http_source=SourceStats(total=1, complete=1, failed=0, pending=0),
            watcher_source=SourceStats(total=0, complete=0, failed=0, pending=0),
            recent_uploads=[
                RecentUploadInfo(
                    capture_id=1,
                    filename=long_filename,
                    status="complete",
                    template_name="journal",
                    created_at=datetime(2026, 1, 20, 11, 0, 0),
                ),
            ],
        )

        presenter = QueueStatusPresenter(string_console)
        presenter.display_http_only(
            http_stats,
            http_enabled=True,
            http_host="localhost",
            http_port=8080,
            http_auth_enabled=False,
        )

        output = string_console._output.getvalue()
        # Filename should be truncated
        assert "..." in output
        # Full filename should not be present
        assert long_filename not in output

    def test_summary_table_styling(self, mock_console, sample_data):
        """Test that summary table uses correct styling."""
        presenter = QueueStatusPresenter(mock_console)

        # Call the private method directly for focused testing
        presenter._print_summary(sample_data.counts)

        # Verify a table was printed
        calls = mock_console.print.call_args_list
        assert len(calls) == 1
        assert isinstance(calls[0][0][0], Table)

    def test_timestamp_printed(self, string_console, sample_data):
        """Test that timestamp is printed."""
        presenter = QueueStatusPresenter(string_console)

        presenter.display_failed_only(sample_data)

        output = string_console._output.getvalue()
        assert "As of:" in output
        assert "UTC" in output

    def test_retry_hints_shown_for_failed(self, string_console, sample_data):
        """Test that retry hints are shown for failed items."""
        presenter = QueueStatusPresenter(string_console)

        presenter.display_failed_only(sample_data)

        output = string_console._output.getvalue()
        assert "python -m src.cli.retry" in output
        assert "--capture-id" in output
        assert "--all-failed" in output


class TestPresenterTableContent:
    """Tests for specific table content rendering."""

    @pytest.fixture
    def string_console(self):
        """Create a real console that writes to a string."""
        output = StringIO()
        # Use no_color=True to avoid ANSI escape codes in tests
        console = Console(file=output, force_terminal=False, width=120, no_color=True)
        console._output = output
        return console

    def test_queue_summary_shows_all_states(self, string_console):
        """Test that summary shows all queue states."""
        counts = QueueCounts(
            pending=5,
            transcribing=2,
            classifying=1,
            posting=1,
            failed=3,
            complete=20,
        )
        data = QueueStatusData(
            counts=counts,
            pending_items=[],
            in_progress_items=[],
            failed_items=[],
        )

        presenter = QueueStatusPresenter(string_console)
        presenter._print_summary(data.counts)

        output = string_console._output.getvalue()

        assert "Pending" in output
        assert "5" in output
        assert "Transcribing" in output
        assert "2" in output
        assert "Classifying" in output
        assert "1" in output
        assert "Posting" in output
        assert "Failed" in output
        assert "3" in output
        assert "Complete" in output
        assert "20" in output
        assert "Total" in output
        assert "32" in output

    def test_upload_sources_table(self, string_console):
        """Test upload sources table content."""
        http_stats = HttpStats(
            http_source=SourceStats(total=10, complete=8, failed=1, pending=1),
            watcher_source=SourceStats(total=25, complete=23, failed=1, pending=1),
            recent_uploads=[],
        )

        presenter = QueueStatusPresenter(string_console)
        presenter._print_http_stats(http_stats)

        output = string_console._output.getvalue()

        assert "Upload Sources" in output
        assert "HTTP Upload" in output
        assert "Folder Watcher" in output
        assert "10" in output  # HTTP total
        assert "25" in output  # Watcher total

    def test_pending_table_shows_device(self, string_console):
        """Test that pending table shows device info."""
        data = QueueStatusData(
            counts=QueueCounts(2, 0, 0, 0, 0, 0),
            pending_items=[
                PendingInfo(
                    capture_id=1,
                    filename="watch_capture.m4a",
                    device="watch",
                    created_at=datetime(2026, 1, 20, 8, 0, 0),
                ),
                PendingInfo(
                    capture_id=2,
                    filename="phone_capture.m4a",
                    device="phone",
                    created_at=datetime(2026, 1, 20, 8, 30, 0),
                ),
            ],
            in_progress_items=[],
            failed_items=[],
        )

        presenter = QueueStatusPresenter(string_console)
        presenter._print_pending_items(data.pending_items)

        output = string_console._output.getvalue()

        assert "watch" in output
        assert "phone" in output
        assert "watch_capture.m4a" in output
        assert "phone_capture.m4a" in output

    def test_in_progress_shows_stage(self, string_console):
        """Test that in-progress table shows stage."""
        data = QueueStatusData(
            counts=QueueCounts(0, 1, 1, 0, 0, 0),
            pending_items=[],
            in_progress_items=[
                InProgressInfo(
                    capture_id=1,
                    filename="transcribing.m4a",
                    stage="transcribing",
                    started_at=datetime(2026, 1, 20, 9, 0, 0),
                ),
                InProgressInfo(
                    capture_id=2,
                    filename="classifying.m4a",
                    stage="classifying",
                    started_at=datetime(2026, 1, 20, 9, 5, 0),
                ),
            ],
            failed_items=[],
        )

        presenter = QueueStatusPresenter(string_console)
        presenter._print_in_progress_items(data.in_progress_items)

        output = string_console._output.getvalue()

        assert "transcribing" in output
        assert "classifying" in output
        assert "In Progress" in output
