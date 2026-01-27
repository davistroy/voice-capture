"""
Unit tests for the pipeline orchestrator module.

Tests cover:
- RetryConfig exponential backoff calculation
- PipelineOrchestrator state machine transitions
- Error handling and retry logic
- File management (move to failed, delete on success)
- Batch processing of pending queue
"""

import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import CaptureRow
from src.models.capture import ProcessingStatus
from src.models.transcription import TranscriptionResult
from src.notion.client import NotionPage, NotionError, CaptureMetadata
from src.pipeline.retry import RetryConfig
from src.pipeline.orchestrator import (
    PipelineOrchestrator,
    ProcessingResult,
    ProcessingStage,
)
from src.transcription.base import TranscriptionError, InvalidAudioError


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_db():
    """Create a mock database instance."""
    db = MagicMock()

    # Make all methods async
    db.get_capture_by_id = AsyncMock()
    db.get_pending_captures = AsyncMock(return_value=[])
    db.update_status = AsyncMock(return_value=True)
    db.update_transcription = AsyncMock(return_value=True)
    db.update_classification = AsyncMock(return_value=True)
    db.update_notion_result = AsyncMock(return_value=True)
    db.mark_complete = AsyncMock(return_value=True)
    db.log_failure = AsyncMock(return_value=1)
    db.increment_retry = AsyncMock(return_value=1)
    db.update_current_path = AsyncMock(return_value=True)

    return db


@pytest.fixture
def mock_transcription():
    """Create a mock transcription service."""
    service = MagicMock()
    service.transcribe = AsyncMock(
        return_value=TranscriptionResult(
            text="This is a test transcription.",
            duration_seconds=10.5,
            language="english",
        )
    )
    return service


@pytest.fixture
def mock_notion():
    """Create a mock Notion service."""
    service = MagicMock()
    service.create_capture_page = AsyncMock(
        return_value=NotionPage(
            id="test-page-id-123",
            url="https://notion.so/test-page-id-123",
        )
    )
    return service


@pytest.fixture
def sample_capture(temp_dir: Path) -> CaptureRow:
    """Create a sample capture record with a real file."""
    # Create actual audio file
    audio_file = temp_dir / "test_audio.m4a"
    audio_file.write_bytes(b"fake audio content")

    return CaptureRow(
        id=1,
        filename="test_audio.m4a",
        original_path=str(audio_file),
        current_path=str(audio_file),
        device="watch",
        captured_at=datetime(2026, 1, 20, 14, 30, 0),
        status="pending",
        retry_count=0,
        transcript=None,
        transcript_duration_seconds=None,
        transcript_language=None,
        template_name=None,
        classification_confidence=None,
        extracted_fields=None,
        suggested_title=None,
        tags=None,
        notion_page_id=None,
        notion_page_url=None,
    )


@pytest.fixture
def orchestrator(mock_db, mock_transcription, mock_notion, temp_dir: Path):
    """Create a pipeline orchestrator with mocked services."""
    return PipelineOrchestrator(
        db=mock_db,
        transcription=mock_transcription,
        notion=mock_notion,
        retry_config=RetryConfig(
            max_retries=3,
            base_backoff_seconds=0.01,  # Fast for tests
        ),
        failed_path=temp_dir / "failed",
    )


# =============================================================================
# RetryConfig Tests
# =============================================================================


class TestRetryConfig:
    """Tests for RetryConfig exponential backoff calculation."""

    def test_default_config_values(self):
        """Verify default retry configuration per TDD Section 5.2."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_backoff_seconds == 5.0
        assert config.max_backoff_seconds == 300.0
        assert config.backoff_multiplier == 2.0
        assert config.jitter_factor == 0.1

    def test_exponential_backoff_without_jitter(self):
        """Verify exponential backoff calculation (ignoring jitter)."""
        config = RetryConfig(
            base_backoff_seconds=5.0,
            backoff_multiplier=2.0,
            jitter_factor=0.0,
        )

        # retry 0: 5 * 2^0 = 5
        assert config.get_backoff(0) == 5.0
        # retry 1: 5 * 2^1 = 10
        assert config.get_backoff(1) == 10.0
        # retry 2: 5 * 2^2 = 20
        assert config.get_backoff(2) == 20.0
        # retry 3: 5 * 2^3 = 40
        assert config.get_backoff(3) == 40.0

    def test_backoff_respects_max_limit(self):
        """Verify backoff is capped at max_backoff_seconds."""
        config = RetryConfig(
            base_backoff_seconds=100.0,
            max_backoff_seconds=300.0,
            backoff_multiplier=2.0,
            jitter_factor=0.0,
        )

        # retry 0: 100 * 2^0 = 100
        assert config.get_backoff(0) == 100.0
        # retry 1: 100 * 2^1 = 200
        assert config.get_backoff(1) == 200.0
        # retry 2: 100 * 2^2 = 400, but capped at 300
        assert config.get_backoff(2) == 300.0
        # retry 10: would be huge, but capped at 300
        assert config.get_backoff(10) == 300.0

    def test_backoff_includes_jitter(self):
        """Verify backoff includes random jitter."""
        config = RetryConfig(
            base_backoff_seconds=10.0,
            jitter_factor=0.1,
            backoff_multiplier=1.0,  # No exponential growth for this test
        )

        # With 10% jitter on 10s base, should be between 10 and 11
        values = [config.get_backoff(0) for _ in range(100)]
        assert all(10.0 <= v <= 11.0 for v in values)
        # Should have some variation (not all exactly the same)
        assert len(set(values)) > 1

    def test_should_retry_within_limit(self):
        """Verify should_retry returns True when retries available."""
        config = RetryConfig(max_retries=3)

        assert config.should_retry(0) is True
        assert config.should_retry(1) is True
        assert config.should_retry(2) is True

    def test_should_retry_at_limit(self):
        """Verify should_retry returns False when at max retries."""
        config = RetryConfig(max_retries=3)

        assert config.should_retry(3) is False
        assert config.should_retry(4) is False


# =============================================================================
# ProcessingResult Tests
# =============================================================================


class TestProcessingResult:
    """Tests for ProcessingResult dataclass."""

    def test_success_result(self):
        """Verify successful result fields."""
        result = ProcessingResult(
            success=True,
            capture_id=42,
            notion_page_id="page-123",
            notion_page_url="https://notion.so/page-123",
        )

        assert result.success is True
        assert result.capture_id == 42
        assert result.notion_page_id == "page-123"
        assert result.error is None
        assert result.stage is None

    def test_failure_result(self):
        """Verify failure result fields."""
        result = ProcessingResult(
            success=False,
            capture_id=42,
            error="Transcription timeout",
            stage="transcribing",
        )

        assert result.success is False
        assert result.capture_id == 42
        assert result.notion_page_id is None
        assert result.error == "Transcription timeout"
        assert result.stage == "transcribing"


# =============================================================================
# PipelineOrchestrator State Machine Tests
# =============================================================================


class TestOrchestratorStateTransitions:
    """Tests for pipeline state machine transitions."""

    @pytest.mark.asyncio
    async def test_full_success_pipeline_phase1(
        self, orchestrator, mock_db, mock_transcription, mock_notion, sample_capture, temp_dir
    ):
        """Verify complete successful pipeline: pending -> transcribing -> posting -> complete."""
        # Setup: capture starts pending
        capture_id = sample_capture.id

        # Simulate state transitions through the pipeline
        states = []

        async def track_status(cid, status, **kwargs):
            states.append(status)
            sample_capture.status = status
            return True

        mock_db.update_status = AsyncMock(side_effect=track_status)

        # Simulate mark_complete setting status
        async def mark_complete(cid):
            sample_capture.status = "complete"
            sample_capture.notion_page_id = "test-page-id-123"
            sample_capture.notion_page_url = "https://notion.so/test-page-id-123"
            return True

        mock_db.mark_complete = AsyncMock(side_effect=mark_complete)

        # After transcription, return updated capture with transcript
        async def get_capture_after_states(cid):
            # Add transcript data after transcribing phase
            if "transcribing" in states:
                sample_capture.transcript = "This is a test transcription."
                sample_capture.transcript_duration_seconds = 10.5
                sample_capture.transcript_language = "english"
            return sample_capture

        mock_db.get_capture_by_id = AsyncMock(side_effect=get_capture_after_states)

        # Process
        result = await orchestrator.process_capture(capture_id)

        # Verify success
        assert result.success is True
        assert result.capture_id == capture_id
        assert result.notion_page_id == "test-page-id-123"
        assert result.error is None

        # Verify state transitions (Phase 1 skips classifying)
        assert "transcribing" in states
        assert "posting" in states

        # Verify services were called
        mock_transcription.transcribe.assert_called_once()
        mock_notion.create_capture_page.assert_called_once()
        mock_db.mark_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_pending_to_transcribing(
        self, orchestrator, mock_db, mock_transcription, sample_capture
    ):
        """Verify pending -> transcribing transition."""
        sample_capture.status = "pending"
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # We'll interrupt after transcribing by raising an exception in posting
        mock_notion = MagicMock()
        mock_notion.create_capture_page = AsyncMock(side_effect=NotionError("Test interrupt"))
        orchestrator._notion = mock_notion

        await orchestrator.process_capture(sample_capture.id)

        # Verify transcribing was set
        calls = [call[0][1] for call in mock_db.update_status.call_args_list]
        assert "transcribing" in calls

    @pytest.mark.asyncio
    async def test_transcribing_to_posting_phase1(
        self, orchestrator, mock_db, mock_transcription, sample_capture
    ):
        """Verify Phase 1 skips classifying: transcribing -> posting."""
        sample_capture.status = "pending"
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Track status updates
        statuses = []
        original_update = mock_db.update_status

        async def track_update(cid, status, **kwargs):
            statuses.append(status)
            sample_capture.status = status
            return True

        mock_db.update_status = AsyncMock(side_effect=track_update)

        await orchestrator.process_capture(sample_capture.id)

        # Verify classifying was skipped
        assert "classifying" not in statuses
        # But transcribing and posting were hit
        assert "transcribing" in statuses
        assert "posting" in statuses

    @pytest.mark.asyncio
    async def test_capture_not_found(self, orchestrator, mock_db):
        """Verify error when capture doesn't exist."""
        mock_db.get_capture_by_id = AsyncMock(return_value=None)

        result = await orchestrator.process_capture(999)

        assert result.success is False
        assert result.capture_id == 999
        assert "not found" in result.error.lower()


# =============================================================================
# Error Handling and Retry Tests
# =============================================================================


class TestOrchestratorErrorHandling:
    """Tests for pipeline error handling and retry logic."""

    @pytest.mark.asyncio
    async def test_transcription_error_increments_retry(
        self, orchestrator, mock_db, mock_transcription, sample_capture
    ):
        """Verify retry count incremented on transcription error."""
        sample_capture.status = "pending"
        sample_capture.retry_count = 0

        async def update_and_return(cid):
            return sample_capture

        mock_db.get_capture_by_id = AsyncMock(side_effect=update_and_return)

        # Fail transcription with retryable error
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        result = await orchestrator.process_capture(sample_capture.id)

        # Should have logged failure and incremented retry
        mock_db.log_failure.assert_called_once()
        mock_db.increment_retry.assert_called_once()

        # Capture should not be marked failed (retry available)
        failed_status_calls = [
            call for call in mock_db.update_status.call_args_list if call[0][1] == "failed"
        ]
        assert len(failed_status_calls) == 0

    @pytest.mark.asyncio
    async def test_invalid_audio_fails_immediately_no_retry(
        self, orchestrator, mock_db, mock_transcription, sample_capture
    ):
        """Verify InvalidAudioError fails immediately without retry."""
        sample_capture.status = "pending"
        sample_capture.retry_count = 0

        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail with non-retryable InvalidAudioError
        mock_transcription.transcribe = AsyncMock(
            side_effect=InvalidAudioError("Invalid format")
        )

        result = await orchestrator.process_capture(sample_capture.id)

        # Should have logged failure
        mock_db.log_failure.assert_called_once()

        # Should NOT have incremented retry (non-retryable)
        mock_db.increment_retry.assert_not_called()

        # Should have moved to failed
        failed_calls = [
            call for call in mock_db.update_status.call_args_list if call[0][1] == "failed"
        ]
        assert len(failed_calls) == 1

    @pytest.mark.asyncio
    async def test_max_retries_moves_to_failed(
        self, orchestrator, mock_db, mock_transcription, sample_capture, temp_dir
    ):
        """Verify capture moves to failed after max retries."""
        sample_capture.status = "pending"
        sample_capture.retry_count = 3  # Already at max

        # Track status changes and update sample_capture accordingly
        async def update_status_and_track(cid, status, **kwargs):
            sample_capture.status = status
            if kwargs.get("error"):
                sample_capture.last_error = kwargs["error"]
            return True

        mock_db.update_status = AsyncMock(side_effect=update_status_and_track)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail transcription
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        result = await orchestrator.process_capture(sample_capture.id)

        # Should NOT have incremented retry (at max)
        mock_db.increment_retry.assert_not_called()

        # Should have moved to failed
        failed_calls = [
            call for call in mock_db.update_status.call_args_list if call[0][1] == "failed"
        ]
        assert len(failed_calls) == 1

        assert result.success is False
        assert result.stage == "transcribing"

    @pytest.mark.asyncio
    async def test_notion_error_retries(
        self, orchestrator, mock_db, mock_transcription, mock_notion, sample_capture
    ):
        """Verify Notion errors trigger retry."""
        sample_capture.status = "posting"
        sample_capture.transcript = "Test transcript"
        sample_capture.transcript_duration_seconds = 10.0
        sample_capture.transcript_language = "english"
        sample_capture.retry_count = 0

        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail Notion with retryable error
        mock_notion.create_capture_page = AsyncMock(
            side_effect=NotionError("Rate limited")
        )
        orchestrator._notion = mock_notion

        result = await orchestrator.process_capture(sample_capture.id)

        # Should have logged failure and incremented retry
        mock_db.log_failure.assert_called_once()
        mock_db.increment_retry.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_logged_to_failure_log(
        self, orchestrator, mock_db, mock_transcription, sample_capture
    ):
        """Verify failures are logged to failure_log table."""
        sample_capture.status = "pending"
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail transcription
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Connection lost", retryable=True)
        )

        await orchestrator.process_capture(sample_capture.id)

        # Verify log_failure was called with correct args
        mock_db.log_failure.assert_called_once()
        call_args = mock_db.log_failure.call_args

        assert call_args.kwargs["capture_id"] == sample_capture.id
        assert call_args.kwargs["stage"] == "transcribing"
        assert call_args.kwargs["error_type"] == "TranscriptionError"
        assert "Connection lost" in call_args.kwargs["error_message"]


# =============================================================================
# File Management Tests
# =============================================================================


class TestOrchestratorFileManagement:
    """Tests for file operations (move to failed, delete on success)."""

    @pytest.mark.asyncio
    async def test_file_moved_to_failed_on_permanent_failure(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify file is moved to /failed/ after max retries."""
        # Create actual file
        inbox = temp_dir / "inbox"
        inbox.mkdir()
        audio_file = inbox / "test.m4a"
        audio_file.write_bytes(b"fake audio")

        failed_dir = temp_dir / "failed"

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(max_retries=3),
            failed_path=failed_dir,
        )

        # Create capture at max retries
        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(audio_file),
            current_path=str(audio_file),
            status="pending",
            retry_count=3,  # At max
        )
        mock_db.get_capture_by_id = AsyncMock(return_value=capture)

        # Fail transcription
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Fail", retryable=True)
        )

        await orchestrator.process_capture(1)

        # Verify file was moved
        assert not audio_file.exists()
        assert (failed_dir / "test.m4a").exists()

        # Verify current_path was updated
        mock_db.update_current_path.assert_called_once()

    @pytest.mark.asyncio
    async def test_source_file_deleted_on_success(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify source audio file is deleted after successful posting."""
        # Create actual file
        processing = temp_dir / "processing"
        processing.mkdir()
        audio_file = processing / "test.m4a"
        audio_file.write_bytes(b"fake audio")

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            failed_path=temp_dir / "failed",
        )

        # Create capture ready for posting
        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(audio_file),
            current_path=str(audio_file),
            status="posting",
            transcript="Test transcript",
            transcript_duration_seconds=10.0,
            transcript_language="english",
            retry_count=0,
        )
        mock_db.get_capture_by_id = AsyncMock(return_value=capture)

        await orchestrator.process_capture(1)

        # Verify file was deleted
        assert not audio_file.exists()

        # Verify mark_complete was called
        mock_db.mark_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_file_handled_gracefully(
        self, orchestrator, mock_db, mock_transcription, sample_capture
    ):
        """Verify missing file is handled gracefully."""
        # Point to non-existent file
        sample_capture.current_path = "/nonexistent/file.m4a"
        sample_capture.original_path = "/nonexistent/file.m4a"

        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Transcription should fail with FileNotFoundError
        mock_transcription.transcribe = AsyncMock(
            side_effect=FileNotFoundError("File not found")
        )

        result = await orchestrator.process_capture(sample_capture.id)

        # Should handle the error
        assert result.success is False
        mock_db.log_failure.assert_called()


# =============================================================================
# Batch Processing Tests
# =============================================================================


class TestOrchestratorBatchProcessing:
    """Tests for batch processing of pending queue."""

    @pytest.mark.asyncio
    async def test_process_pending_queue_empty(self, orchestrator, mock_db):
        """Verify empty queue returns empty results."""
        mock_db.get_pending_captures = AsyncMock(return_value=[])

        results = await orchestrator.process_pending_queue()

        assert results == []

    @pytest.mark.asyncio
    async def test_process_pending_queue_multiple_captures(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify multiple captures are processed sequentially."""
        # Create files for captures
        processing = temp_dir / "processing"
        processing.mkdir()

        captures = []
        for i in range(3):
            audio_file = processing / f"test_{i}.m4a"
            audio_file.write_bytes(b"fake audio")
            captures.append(
                CaptureRow(
                    id=i + 1,
                    filename=f"test_{i}.m4a",
                    original_path=str(audio_file),
                    current_path=str(audio_file),
                    status="pending",
                    retry_count=0,
                )
            )

        mock_db.get_pending_captures = AsyncMock(return_value=captures)

        # Track status updates per capture
        capture_states = {c.id: c for c in captures}

        async def update_status(cid, status, **kwargs):
            if cid in capture_states:
                capture_states[cid].status = status
            return True

        async def mark_complete(cid):
            if cid in capture_states:
                capture_states[cid].status = "complete"
                capture_states[cid].notion_page_id = f"page-{cid}"
                capture_states[cid].notion_page_url = f"https://notion.so/page-{cid}"
            return True

        mock_db.update_status = AsyncMock(side_effect=update_status)
        mock_db.mark_complete = AsyncMock(side_effect=mark_complete)

        # Return appropriate capture for each get_capture_by_id call
        def get_capture(cid):
            return capture_states.get(cid)

        mock_db.get_capture_by_id = AsyncMock(side_effect=get_capture)

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(base_backoff_seconds=0.001),
            failed_path=temp_dir / "failed",
        )

        results = await orchestrator.process_pending_queue()

        assert len(results) == 3
        assert all(r.success for r in results)

        # Verify transcription called for each
        assert mock_transcription.transcribe.call_count == 3

        # Verify Notion called for each
        assert mock_notion.create_capture_page.call_count == 3

    @pytest.mark.asyncio
    async def test_process_pending_applies_backoff_for_retries(
        self, mock_db, mock_transcription, mock_notion, temp_dir
    ):
        """Verify backoff is applied between retries in batch processing."""
        processing = temp_dir / "processing"
        processing.mkdir()

        audio_file = processing / "test.m4a"
        audio_file.write_bytes(b"fake audio")

        capture = CaptureRow(
            id=1,
            filename="test.m4a",
            original_path=str(audio_file),
            current_path=str(audio_file),
            status="pending",
            retry_count=2,  # Has been retried before
        )

        mock_db.get_pending_captures = AsyncMock(return_value=[capture])
        mock_db.get_capture_by_id = AsyncMock(return_value=capture)

        # Use very short backoff to verify it's applied
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            retry_config=RetryConfig(base_backoff_seconds=0.05, jitter_factor=0),
            failed_path=temp_dir / "failed",
        )

        import time

        start = time.time()
        await orchestrator.process_pending_queue()
        elapsed = time.time() - start

        # Should have waited ~0.05 * 2^1 = 0.1 seconds for retry backoff
        # (retry_count is 2, so we use 2-1=1 for backoff calculation)
        assert elapsed >= 0.05


# =============================================================================
# Manual Retry Tests
# =============================================================================


class TestOrchestratorManualRetry:
    """Tests for manual retry functionality."""

    @pytest.mark.asyncio
    async def test_retry_failed_capture(
        self, orchestrator, mock_db, sample_capture
    ):
        """Verify retry_failed resets status and reprocesses."""
        sample_capture.status = "failed"
        sample_capture.last_error = "Previous error"

        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        result = await orchestrator.retry_failed(sample_capture.id)

        # Should have reset status to pending
        reset_call = mock_db.update_status.call_args_list[0]
        assert reset_call[0][1] == "pending"
        assert reset_call.kwargs.get("error") is None

    @pytest.mark.asyncio
    async def test_retry_failed_from_specific_stage(
        self, orchestrator, mock_db, sample_capture
    ):
        """Verify retry_failed can restart from specific stage."""
        sample_capture.status = "failed"
        sample_capture.transcript = "Existing transcript"
        sample_capture.transcript_duration_seconds = 10.0
        sample_capture.transcript_language = "english"

        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        result = await orchestrator.retry_failed(sample_capture.id, from_stage="posting")

        # Should have reset status to posting
        reset_call = mock_db.update_status.call_args_list[0]
        assert reset_call[0][1] == "posting"

    @pytest.mark.asyncio
    async def test_retry_failed_capture_not_found(self, orchestrator, mock_db):
        """Verify retry_failed handles missing capture."""
        mock_db.get_capture_by_id = AsyncMock(return_value=None)

        result = await orchestrator.retry_failed(999)

        assert result.success is False
        assert "not found" in result.error.lower()


# =============================================================================
# Title Generation Tests (Work item 6.6: Now uses TextFormatter)
# =============================================================================


class TestOrchestratorTitleGeneration:
    """Tests for title generation from transcript.

    Work item 6.6: Title generation was extracted to TextFormatter class.
    These tests verify the TextFormatter is correctly integrated.
    """

    def test_generate_title_from_short_transcript(self):
        """Verify title from short transcript."""
        from src.pipeline.text_formatter import TextFormatter
        title = TextFormatter.generate_title("Hello world.")
        assert title == "Hello world."

    def test_generate_title_truncates_long_transcript(self):
        """Verify long transcripts are truncated to ~15 words."""
        from src.pipeline.text_formatter import TextFormatter
        long_text = " ".join(["word"] * 50)
        title = TextFormatter.generate_title(long_text)

        words = title.replace("...", "").strip().split()
        assert len(words) <= 15

    def test_generate_title_uses_first_sentence(self):
        """Verify only first sentence is used."""
        from src.pipeline.text_formatter import TextFormatter
        text = "This is the first sentence. This is the second."
        title = TextFormatter.generate_title(text)
        assert title == "This is the first sentence."

    def test_generate_title_handles_none(self):
        """Verify None transcript produces default title."""
        from src.pipeline.text_formatter import TextFormatter
        title = TextFormatter.generate_title(None)
        assert title == "Voice Capture"

    def test_generate_title_handles_empty(self):
        """Verify empty transcript produces default title."""
        from src.pipeline.text_formatter import TextFormatter
        title = TextFormatter.generate_title("")
        assert title == "Voice Capture"


# =============================================================================
# Device Formatting Tests (Work item 6.6: Now uses TextFormatter)
# =============================================================================


class TestOrchestratorDeviceFormatting:
    """Tests for device string formatting.

    Work item 6.6: Device formatting was extracted to TextFormatter class.
    Device passthrough: raw device strings are returned as-is.
    """

    def test_format_device_passthrough(self):
        """Verify device strings are passed through as-is."""
        from src.pipeline.text_formatter import TextFormatter
        assert TextFormatter.format_device_name("watch") == "watch"
        assert TextFormatter.format_device_name("Apple Watch") == "Apple Watch"
        assert TextFormatter.format_device_name("iPhone") == "iPhone"

    def test_format_device_fallback(self):
        """Verify None/empty defaults to 'Unknown'."""
        from src.pipeline.text_formatter import TextFormatter
        assert TextFormatter.format_device_name(None) == "Unknown"
        assert TextFormatter.format_device_name("") == "Unknown"


# =============================================================================
# Notification Integration Tests
# =============================================================================


@pytest.fixture
def mock_notifications():
    """Create a mock notification service."""
    service = MagicMock()
    service.notify_processing_failure = AsyncMock(return_value=True)
    service.send_daily_summary = AsyncMock(return_value=True)
    service.notify_high_failure_rate = AsyncMock(return_value=True)
    service.notify_queue_backup = AsyncMock(return_value=True)
    return service


@pytest.fixture
def orchestrator_with_notifications(
    mock_db, mock_transcription, mock_notion, mock_notifications, temp_dir
):
    """Create a pipeline orchestrator with notification service."""
    return PipelineOrchestrator(
        db=mock_db,
        transcription=mock_transcription,
        notion=mock_notion,
        retry_config=RetryConfig(
            max_retries=3,
            base_backoff_seconds=0.01,  # Fast for tests
        ),
        failed_path=temp_dir / "failed",
        notifications=mock_notifications,
    )


class TestOrchestratorNotifications:
    """Tests for notification integration in pipeline orchestrator."""

    @pytest.mark.asyncio
    async def test_notification_sent_after_max_retries(
        self,
        orchestrator_with_notifications,
        mock_db,
        mock_transcription,
        mock_notifications,
        sample_capture,
    ):
        """Verify failure notification is sent after max retries exhausted."""
        sample_capture.status = "pending"
        sample_capture.retry_count = 3  # At max retries

        async def update_status_and_track(cid, status, **kwargs):
            sample_capture.status = status
            if kwargs.get("error"):
                sample_capture.last_error = kwargs["error"]
            return True

        mock_db.update_status = AsyncMock(side_effect=update_status_and_track)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail transcription with retryable error
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        await orchestrator_with_notifications.process_capture(sample_capture.id)

        # Verify notification was sent
        mock_notifications.notify_processing_failure.assert_called_once()
        call_args = mock_notifications.notify_processing_failure.call_args

        assert call_args.kwargs["filename"] == sample_capture.filename
        assert call_args.kwargs["stage"] == "transcribing"
        assert "Timeout" in call_args.kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_notification_sent_for_non_retryable_error(
        self,
        orchestrator_with_notifications,
        mock_db,
        mock_transcription,
        mock_notifications,
        sample_capture,
    ):
        """Verify failure notification is sent for non-retryable errors."""
        sample_capture.status = "pending"
        sample_capture.retry_count = 0

        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail with non-retryable InvalidAudioError
        mock_transcription.transcribe = AsyncMock(
            side_effect=InvalidAudioError("Invalid format")
        )

        await orchestrator_with_notifications.process_capture(sample_capture.id)

        # Verify notification was sent
        mock_notifications.notify_processing_failure.assert_called_once()
        call_args = mock_notifications.notify_processing_failure.call_args

        assert call_args.kwargs["filename"] == sample_capture.filename
        assert call_args.kwargs["stage"] == "transcribing"

    @pytest.mark.asyncio
    async def test_no_notification_when_retries_remain(
        self,
        orchestrator_with_notifications,
        mock_db,
        mock_transcription,
        mock_notifications,
        sample_capture,
    ):
        """Verify no notification is sent when retries are still available."""
        sample_capture.status = "pending"
        sample_capture.retry_count = 0  # Retries available

        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail with retryable error
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        await orchestrator_with_notifications.process_capture(sample_capture.id)

        # Verify no notification was sent
        mock_notifications.notify_processing_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_duplicate_notifications_for_same_failure(
        self,
        orchestrator_with_notifications,
        mock_db,
        mock_transcription,
        mock_notifications,
        sample_capture,
    ):
        """Verify duplicate notifications are prevented for the same capture."""
        sample_capture.status = "pending"
        sample_capture.retry_count = 3  # At max retries

        async def update_status_and_track(cid, status, **kwargs):
            sample_capture.status = status
            return True

        mock_db.update_status = AsyncMock(side_effect=update_status_and_track)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail transcription
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        # Process twice (simulating somehow hitting the failure path twice)
        await orchestrator_with_notifications.process_capture(sample_capture.id)

        # Reset status and process again to try to trigger second notification
        sample_capture.status = "pending"
        await orchestrator_with_notifications.process_capture(sample_capture.id)

        # Should only have been called once due to duplicate prevention
        assert mock_notifications.notify_processing_failure.call_count == 1

    @pytest.mark.asyncio
    async def test_notification_includes_notion_url_when_available(
        self,
        orchestrator_with_notifications,
        mock_db,
        mock_transcription,
        mock_notion,
        mock_notifications,
        sample_capture,
    ):
        """Verify Notion page URL is included in notification when available."""
        # Set up capture that failed after posting (has Notion URL)
        sample_capture.status = "posting"
        sample_capture.transcript = "Test transcript"
        sample_capture.transcript_duration_seconds = 10.0
        sample_capture.transcript_language = "english"
        sample_capture.retry_count = 3  # At max retries
        sample_capture.notion_page_url = "https://notion.so/test-page-123"

        async def update_status_and_track(cid, status, **kwargs):
            sample_capture.status = status
            return True

        mock_db.update_status = AsyncMock(side_effect=update_status_and_track)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail Notion posting
        mock_notion.create_capture_page = AsyncMock(
            side_effect=NotionError("Rate limited")
        )
        orchestrator_with_notifications._notion = mock_notion

        await orchestrator_with_notifications.process_capture(sample_capture.id)

        # Verify notification includes Notion URL
        mock_notifications.notify_processing_failure.assert_called_once()
        call_args = mock_notifications.notify_processing_failure.call_args

        assert call_args.kwargs["notion_page_url"] == "https://notion.so/test-page-123"

    @pytest.mark.asyncio
    async def test_no_notification_when_service_not_configured(
        self,
        orchestrator,  # Uses the regular orchestrator without notifications
        mock_db,
        mock_transcription,
        sample_capture,
    ):
        """Verify no errors when notification service is not configured."""
        sample_capture.status = "pending"
        sample_capture.retry_count = 3  # At max retries

        async def update_status_and_track(cid, status, **kwargs):
            sample_capture.status = status
            return True

        mock_db.update_status = AsyncMock(side_effect=update_status_and_track)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail transcription
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        # Should not raise even without notification service
        result = await orchestrator.process_capture(sample_capture.id)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_affect_pipeline(
        self,
        orchestrator_with_notifications,
        mock_db,
        mock_transcription,
        mock_notifications,
        sample_capture,
    ):
        """Verify notification failures don't affect pipeline operation."""
        sample_capture.status = "pending"
        sample_capture.retry_count = 3  # At max retries

        async def update_status_and_track(cid, status, **kwargs):
            sample_capture.status = status
            return True

        mock_db.update_status = AsyncMock(side_effect=update_status_and_track)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail transcription
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        # Make notification service fail
        mock_notifications.notify_processing_failure = AsyncMock(
            side_effect=Exception("Notification service unavailable")
        )

        # Should not raise despite notification failure
        result = await orchestrator_with_notifications.process_capture(sample_capture.id)

        assert result.success is False
        assert result.stage == "transcribing"

    @pytest.mark.asyncio
    async def test_retry_failed_clears_notification_tracking(
        self,
        orchestrator_with_notifications,
        mock_db,
        mock_transcription,
        mock_notion,
        mock_notifications,
        sample_capture,
        temp_dir,
    ):
        """Verify retry_failed clears notification tracking for re-notification."""
        # First, cause a failure and notification
        sample_capture.status = "pending"
        sample_capture.retry_count = 3  # At max retries

        async def update_status_and_track(cid, status, **kwargs):
            sample_capture.status = status
            return True

        mock_db.update_status = AsyncMock(side_effect=update_status_and_track)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture)

        # Fail transcription
        mock_transcription.transcribe = AsyncMock(
            side_effect=TranscriptionError("Timeout", retryable=True)
        )

        await orchestrator_with_notifications.process_capture(sample_capture.id)

        # Verify first notification sent
        assert mock_notifications.notify_processing_failure.call_count == 1

        # Now retry the capture
        sample_capture.status = "failed"
        mock_notifications.notify_processing_failure.reset_mock()

        await orchestrator_with_notifications.retry_failed(sample_capture.id)

        # Should have sent another notification since tracking was cleared
        assert mock_notifications.notify_processing_failure.call_count == 1

    def test_clear_notification_tracking_specific(self, orchestrator_with_notifications):
        """Verify clear_notification_tracking clears specific capture."""
        orchestrator_with_notifications._notified_failures.add(1)
        orchestrator_with_notifications._notified_failures.add(2)

        orchestrator_with_notifications.clear_notification_tracking(1)

        assert 1 not in orchestrator_with_notifications._notified_failures
        assert 2 in orchestrator_with_notifications._notified_failures

    def test_clear_notification_tracking_all(self, orchestrator_with_notifications):
        """Verify clear_notification_tracking clears all when capture_id is None."""
        orchestrator_with_notifications._notified_failures.add(1)
        orchestrator_with_notifications._notified_failures.add(2)

        orchestrator_with_notifications.clear_notification_tracking()

        assert len(orchestrator_with_notifications._notified_failures) == 0
