"""
Unit tests for pipeline orchestrator with classification integration.

Tests cover:
- Full pipeline with classification service
- Classification state machine transitions
- Classification error handling and retry
- Classification result storage in database
- Template-specific Notion page creation
"""

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import CaptureRow
from src.models.classification import ClassificationResult
from src.models.transcription import TranscriptionResult
from src.notion.client import NotionPage, NotionError, CaptureMetadata
from src.pipeline.retry import RetryConfig
from src.pipeline.orchestrator import (
    PipelineOrchestrator,
    ProcessingResult,
    ProcessingStage,
)
from src.transcription.base import TranscriptionError


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
            text="I need to review the quarterly report by Friday.",
            duration_seconds=15.5,
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
def mock_classification():
    """Create a mock classification service."""
    service = MagicMock()
    service.classify = AsyncMock(
        return_value=ClassificationResult(
            template_name="task",
            confidence=0.87,
            fields={
                "priority": "High",
                "context": "Quarterly review",
                "due_date": "2026-01-24",
            },
            title="Review quarterly report by Friday",
            tags=["work", "quarterly-review", "deadline"],
            reasoning="Task identified due to imperative statement and deadline",
        )
    )
    return service


@pytest.fixture
def mock_template_loader():
    """Create a mock template loader."""
    loader = MagicMock()

    # Create a mock template config
    mock_template = MagicMock()
    mock_template.name = "task"
    mock_template.display_name = "Task"
    mock_template.fields = []
    mock_template.page_body_template = "## Context\n{{ context }}"
    mock_template.enabled = True

    loader.get_template = MagicMock(return_value=mock_template)
    loader.get_enabled_templates = MagicMock(return_value=[mock_template])
    loader.get_fallback_template = MagicMock(return_value=mock_template)

    return loader


@pytest.fixture
def sample_capture_pending(temp_dir: Path) -> CaptureRow:
    """Create a sample capture record in pending state with a real file."""
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
def sample_capture_transcribed(temp_dir: Path) -> CaptureRow:
    """Create a sample capture record in classifying state after transcription."""
    audio_file = temp_dir / "test_audio.m4a"
    audio_file.write_bytes(b"fake audio content")

    return CaptureRow(
        id=1,
        filename="test_audio.m4a",
        original_path=str(audio_file),
        current_path=str(audio_file),
        device="watch",
        captured_at=datetime(2026, 1, 20, 14, 30, 0),
        status="classifying",
        retry_count=0,
        transcript="I need to review the quarterly report by Friday.",
        transcript_duration_seconds=15.5,
        transcript_language="english",
        template_name=None,
        classification_confidence=None,
        extracted_fields=None,
        suggested_title=None,
        tags=None,
        notion_page_id=None,
        notion_page_url=None,
    )


@pytest.fixture
def sample_capture_classified(temp_dir: Path) -> CaptureRow:
    """Create a sample capture record in posting state after classification."""
    audio_file = temp_dir / "test_audio.m4a"
    audio_file.write_bytes(b"fake audio content")

    return CaptureRow(
        id=1,
        filename="test_audio.m4a",
        original_path=str(audio_file),
        current_path=str(audio_file),
        device="watch",
        captured_at=datetime(2026, 1, 20, 14, 30, 0),
        status="posting",
        retry_count=0,
        transcript="I need to review the quarterly report by Friday.",
        transcript_duration_seconds=15.5,
        transcript_language="english",
        template_name="task",
        classification_confidence=0.87,
        extracted_fields={
            "priority": "High",
            "context": "Quarterly review",
            "due_date": "2026-01-24",
        },
        suggested_title="Review quarterly report by Friday",
        tags=["work", "quarterly-review", "deadline"],
        notion_page_id=None,
        notion_page_url=None,
    )


@pytest.fixture
def orchestrator_with_classification(
    mock_db,
    mock_transcription,
    mock_notion,
    mock_classification,
    mock_template_loader,
    temp_dir: Path,
):
    """Create a pipeline orchestrator with classification service (Phase 2+)."""
    return PipelineOrchestrator(
        db=mock_db,
        transcription=mock_transcription,
        notion=mock_notion,
        classification=mock_classification,
        template_loader=mock_template_loader,
        retry_config=RetryConfig(
            max_retries=3,
            base_backoff_seconds=0.01,  # Fast for tests
        ),
        failed_path=temp_dir / "failed",
    )


# =============================================================================
# Full Pipeline with Classification Tests
# =============================================================================


class TestPipelineWithClassification:
    """Tests for full pipeline with classification enabled."""

    @pytest.mark.asyncio
    async def test_full_success_pipeline_with_classification(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_transcription,
        mock_classification,
        mock_notion,
        sample_capture_pending,
        temp_dir,
    ):
        """Verify complete pipeline: pending -> transcribing -> classifying -> posting -> complete."""
        capture_id = sample_capture_pending.id
        states = []

        async def track_status(cid, status, **kwargs):
            states.append(status)
            sample_capture_pending.status = status
            if status == "classifying":
                # After transcription, add transcript data
                sample_capture_pending.transcript = "I need to review the quarterly report by Friday."
                sample_capture_pending.transcript_duration_seconds = 15.5
                sample_capture_pending.transcript_language = "english"
            elif status == "posting":
                # After classification, add classification data
                sample_capture_pending.template_name = "task"
                sample_capture_pending.classification_confidence = 0.87
                sample_capture_pending.extracted_fields = {"priority": "High"}
                sample_capture_pending.suggested_title = "Review quarterly report"
                sample_capture_pending.tags = ["work"]
            return True

        mock_db.update_status = AsyncMock(side_effect=track_status)

        async def mark_complete(cid):
            sample_capture_pending.status = "complete"
            sample_capture_pending.notion_page_id = "test-page-id-123"
            sample_capture_pending.notion_page_url = "https://notion.so/test-page-id-123"
            return True

        mock_db.mark_complete = AsyncMock(side_effect=mark_complete)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_pending)

        # Process
        result = await orchestrator_with_classification.process_capture(capture_id)

        # Verify success
        assert result.success is True
        assert result.capture_id == capture_id
        assert result.notion_page_id == "test-page-id-123"
        assert result.error is None

        # Verify state transitions include classifying
        assert "transcribing" in states
        assert "classifying" in states
        assert "posting" in states

        # Verify all services were called
        mock_transcription.transcribe.assert_called_once()
        mock_classification.classify.assert_called_once()
        mock_notion.create_capture_page.assert_called_once()
        mock_db.mark_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_classification_service_called_with_correct_params(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_classification,
        sample_capture_transcribed,
    ):
        """Verify classification service receives correct transcript and metadata."""
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_transcribed)

        await orchestrator_with_classification.process_capture(sample_capture_transcribed.id)

        # Verify classify was called
        mock_classification.classify.assert_called_once()

        # Check call arguments
        call_args = mock_classification.classify.call_args
        assert call_args.kwargs["transcript"] == sample_capture_transcribed.transcript

        # Check metadata
        metadata = call_args.kwargs["metadata"]
        assert metadata.captured_at == sample_capture_transcribed.captured_at
        assert metadata.duration_seconds == sample_capture_transcribed.transcript_duration_seconds
        assert metadata.device == sample_capture_transcribed.device


# =============================================================================
# Classification State Transition Tests
# =============================================================================


class TestClassificationStateTransitions:
    """Tests for classification state machine transitions."""

    @pytest.mark.asyncio
    async def test_transcribing_to_classifying_transition(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_transcription,
        sample_capture_pending,
    ):
        """Verify transcribing -> classifying transition when classification service present."""
        sample_capture_pending.status = "pending"

        statuses = []

        async def track_update(cid, status, **kwargs):
            statuses.append(status)
            sample_capture_pending.status = status
            if status == "classifying":
                sample_capture_pending.transcript = "Test transcript"
                sample_capture_pending.transcript_duration_seconds = 10.0
                sample_capture_pending.transcript_language = "english"
            return True

        mock_db.update_status = AsyncMock(side_effect=track_update)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_pending)

        await orchestrator_with_classification.process_capture(sample_capture_pending.id)

        # Verify classifying state was reached
        assert "transcribing" in statuses
        assert "classifying" in statuses

    @pytest.mark.asyncio
    async def test_classifying_to_posting_transition(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_classification,
        sample_capture_transcribed,
    ):
        """Verify classifying -> posting transition."""
        statuses = []

        async def track_update(cid, status, **kwargs):
            statuses.append(status)
            sample_capture_transcribed.status = status
            if status == "posting":
                sample_capture_transcribed.template_name = "task"
                sample_capture_transcribed.classification_confidence = 0.87
                sample_capture_transcribed.extracted_fields = {}
                sample_capture_transcribed.suggested_title = "Test"
                sample_capture_transcribed.tags = []
            return True

        mock_db.update_status = AsyncMock(side_effect=track_update)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_transcribed)

        await orchestrator_with_classification.process_capture(sample_capture_transcribed.id)

        # Verify posting state was reached after classification
        assert "posting" in statuses


# =============================================================================
# Classification Error Handling Tests
# =============================================================================


class TestClassificationErrorHandling:
    """Tests for classification error handling and retry logic."""

    @pytest.mark.asyncio
    async def test_classification_error_increments_retry(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_classification,
        sample_capture_transcribed,
    ):
        """Verify retry count incremented on classification error."""
        sample_capture_transcribed.retry_count = 0
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_transcribed)

        # Fail classification with retryable error
        mock_classification.classify = AsyncMock(
            side_effect=Exception("API timeout")
        )

        result = await orchestrator_with_classification.process_capture(
            sample_capture_transcribed.id
        )

        # Should have logged failure and incremented retry
        mock_db.log_failure.assert_called_once()
        mock_db.increment_retry.assert_called_once()

        # Verify failure log was for classifying stage
        call_kwargs = mock_db.log_failure.call_args.kwargs
        assert call_kwargs["stage"] == "classifying"

    @pytest.mark.asyncio
    async def test_classification_max_retries_moves_to_failed(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_classification,
        sample_capture_transcribed,
        temp_dir,
    ):
        """Verify capture moves to failed after max retries in classification."""
        sample_capture_transcribed.retry_count = 3  # At max retries

        async def update_status_track(cid, status, **kwargs):
            sample_capture_transcribed.status = status
            if kwargs.get("error"):
                sample_capture_transcribed.last_error = kwargs["error"]
            return True

        mock_db.update_status = AsyncMock(side_effect=update_status_track)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_transcribed)

        # Fail classification
        mock_classification.classify = AsyncMock(
            side_effect=Exception("Persistent failure")
        )

        result = await orchestrator_with_classification.process_capture(
            sample_capture_transcribed.id
        )

        # Should NOT have incremented retry (at max)
        mock_db.increment_retry.assert_not_called()

        # Should have moved to failed
        failed_calls = [
            call for call in mock_db.update_status.call_args_list
            if call[0][1] == "failed"
        ]
        assert len(failed_calls) == 1

        assert result.success is False
        assert result.stage == "classifying"

    @pytest.mark.asyncio
    async def test_classification_error_logs_to_failure_log(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_classification,
        sample_capture_transcribed,
    ):
        """Verify classification failures are logged to failure_log table."""
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_transcribed)

        # Fail classification with specific error
        mock_classification.classify = AsyncMock(
            side_effect=ValueError("Invalid JSON response from Claude")
        )

        await orchestrator_with_classification.process_capture(
            sample_capture_transcribed.id
        )

        # Verify log_failure was called with correct args
        mock_db.log_failure.assert_called_once()
        call_kwargs = mock_db.log_failure.call_args.kwargs

        assert call_kwargs["capture_id"] == sample_capture_transcribed.id
        assert call_kwargs["stage"] == "classifying"
        assert call_kwargs["error_type"] == "ValueError"
        assert "Invalid JSON" in call_kwargs["error_message"]


# =============================================================================
# Classification Result Storage Tests
# =============================================================================


class TestClassificationResultStorage:
    """Tests for storing classification results in database."""

    @pytest.mark.asyncio
    async def test_classification_result_stored_in_database(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_classification,
        sample_capture_transcribed,
    ):
        """Verify classification result is stored correctly in database."""
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_transcribed)

        # Setup classification result
        expected_result = ClassificationResult(
            template_name="task",
            confidence=0.87,
            fields={"priority": "High", "context": "Quarterly review"},
            title="Review quarterly report by Friday",
            tags=["work", "deadline"],
            reasoning="Task due to imperative statement",
        )
        mock_classification.classify = AsyncMock(return_value=expected_result)

        await orchestrator_with_classification.process_capture(
            sample_capture_transcribed.id
        )

        # Verify update_classification was called with correct values
        mock_db.update_classification.assert_called_once()
        call_kwargs = mock_db.update_classification.call_args.kwargs

        assert call_kwargs["capture_id"] == sample_capture_transcribed.id
        assert call_kwargs["template"] == "task"
        assert call_kwargs["confidence"] == 0.87
        assert call_kwargs["fields"] == {"priority": "High", "context": "Quarterly review"}
        assert call_kwargs["title"] == "Review quarterly report by Friday"
        assert call_kwargs["tags"] == ["work", "deadline"]

    @pytest.mark.asyncio
    async def test_low_confidence_uses_general_template(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_classification,
        sample_capture_transcribed,
    ):
        """Verify low confidence classification returns general template from service."""
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_transcribed)

        # Classification service returns general due to low confidence
        # (the service handles the threshold internally)
        low_confidence_result = ClassificationResult(
            template_name="general",
            confidence=0.65,
            fields={},
            title="Voice capture note",
            tags=["note"],
            reasoning="Low confidence, using fallback",
        )
        mock_classification.classify = AsyncMock(return_value=low_confidence_result)

        await orchestrator_with_classification.process_capture(
            sample_capture_transcribed.id
        )

        # Verify general template was stored
        call_kwargs = mock_db.update_classification.call_args.kwargs
        assert call_kwargs["template"] == "general"
        assert call_kwargs["confidence"] == 0.65


# =============================================================================
# Template-Specific Notion Page Creation Tests
# =============================================================================


class TestTemplateSpecificNotionPage:
    """Tests for template-specific Notion page creation."""

    @pytest.mark.asyncio
    async def test_notion_receives_classification_and_template(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_notion,
        mock_template_loader,
        sample_capture_classified,
    ):
        """Verify Notion service receives classification result and template."""
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_classified)

        await orchestrator_with_classification.process_capture(
            sample_capture_classified.id
        )

        # Verify create_capture_page was called
        mock_notion.create_capture_page.assert_called_once()

        # Check call arguments include classification and template
        call_kwargs = mock_notion.create_capture_page.call_args.kwargs

        # Should have classification result
        assert "classification" in call_kwargs
        classification = call_kwargs["classification"]
        assert classification is not None
        assert classification.template_name == "task"
        assert classification.confidence == 0.87

        # Should have template config
        assert "template" in call_kwargs
        template = call_kwargs["template"]
        assert template is not None
        assert template.name == "task"

    @pytest.mark.asyncio
    async def test_basic_page_when_template_not_found(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_notion,
        mock_template_loader,
        sample_capture_classified,
    ):
        """Verify basic page creation when template is not found in loader."""
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_classified)

        # Template loader returns None (template not found)
        mock_template_loader.get_template = MagicMock(return_value=None)

        await orchestrator_with_classification.process_capture(
            sample_capture_classified.id
        )

        # Verify create_capture_page was called without classification/template
        call_kwargs = mock_notion.create_capture_page.call_args.kwargs
        assert call_kwargs.get("classification") is None

    @pytest.mark.asyncio
    async def test_posting_without_template_loader_uses_basic_page(
        self,
        mock_db,
        mock_transcription,
        mock_notion,
        mock_classification,
        sample_capture_classified,
        temp_dir,
    ):
        """Verify basic page creation when no template loader is provided."""
        # Create orchestrator without template_loader
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=mock_transcription,
            notion=mock_notion,
            classification=mock_classification,
            template_loader=None,  # No template loader
            retry_config=RetryConfig(base_backoff_seconds=0.01),
            failed_path=temp_dir / "failed",
        )

        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_classified)

        await orchestrator.process_capture(sample_capture_classified.id)

        # Should still create page, but without classification/template
        mock_notion.create_capture_page.assert_called_once()
        call_kwargs = mock_notion.create_capture_page.call_args.kwargs
        assert call_kwargs.get("classification") is None
        assert call_kwargs.get("template") is None


# =============================================================================
# Integration Tests
# =============================================================================


class TestPipelineClassificationIntegration:
    """Integration tests for classification in the pipeline."""

    @pytest.mark.asyncio
    async def test_end_to_end_with_all_templates(
        self,
        mock_db,
        mock_transcription,
        mock_classification,
        mock_notion,
        mock_template_loader,
        temp_dir,
    ):
        """Verify end-to-end processing with different template classifications."""
        test_cases = [
            ("task", 0.90, {"priority": "High"}),
            ("journal", 0.85, {"mood": "positive"}),
            ("idea", 0.78, {"potential_value": "High"}),
            ("research", 0.82, {"status": "Not Started"}),
            ("product", 0.88, {"type": "feature"}),
            ("general", 0.65, {}),
        ]

        for template_name, confidence, fields in test_cases:
            # Create fresh audio file for each iteration
            audio_file = temp_dir / f"test_{template_name}.m4a"
            audio_file.write_bytes(b"fake audio content")

            # Create fresh capture for each test case
            capture = CaptureRow(
                id=1,
                filename=f"test_{template_name}.m4a",
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

            # Create fresh orchestrator for each test
            orchestrator = PipelineOrchestrator(
                db=mock_db,
                transcription=mock_transcription,
                notion=mock_notion,
                classification=mock_classification,
                template_loader=mock_template_loader,
                retry_config=RetryConfig(base_backoff_seconds=0.01),
                failed_path=temp_dir / "failed",
            )

            # Configure mock for this test case
            mock_classification.classify = AsyncMock(
                return_value=ClassificationResult(
                    template_name=template_name,
                    confidence=confidence,
                    fields=fields,
                    title=f"Test {template_name}",
                    tags=[template_name],
                    reasoning=f"Classified as {template_name}",
                )
            )

            # Track status updates
            async def make_update_status(cap, tname, conf, flds):
                async def update_status(cid, status, **kwargs):
                    cap.status = status
                    if status == "classifying":
                        cap.transcript = "Test transcript"
                        cap.transcript_duration_seconds = 10.0
                        cap.transcript_language = "english"
                    if status == "posting":
                        cap.template_name = tname
                        cap.classification_confidence = conf
                        cap.extracted_fields = flds
                    return True
                return update_status

            async def make_mark_complete(cap):
                async def mark_complete(cid):
                    cap.status = "complete"
                    cap.notion_page_id = "page-id"
                    cap.notion_page_url = "https://notion.so/page"
                    return True
                return mark_complete

            mock_db.update_status = AsyncMock(
                side_effect=await make_update_status(capture, template_name, confidence, fields)
            )
            mock_db.mark_complete = AsyncMock(
                side_effect=await make_mark_complete(capture)
            )
            mock_db.get_capture_by_id = AsyncMock(return_value=capture)
            mock_db.update_classification.reset_mock()

            # Process
            result = await orchestrator.process_capture(capture.id)

            # Verify success
            assert result.success is True, f"Failed for template: {template_name}"

            # Verify classification was stored with correct template
            mock_db.update_classification.assert_called_once()
            stored_template = mock_db.update_classification.call_args.kwargs["template"]
            assert stored_template == template_name, f"Expected {template_name}, got {stored_template}"

    @pytest.mark.asyncio
    async def test_resume_from_classifying_state(
        self,
        orchestrator_with_classification,
        mock_db,
        mock_classification,
        mock_notion,
        sample_capture_transcribed,
    ):
        """Verify processing can resume from classifying state after restart."""
        # Capture is in classifying state (e.g., after service restart)
        sample_capture_transcribed.status = "classifying"

        async def track_status(cid, status, **kwargs):
            sample_capture_transcribed.status = status
            if status == "posting":
                sample_capture_transcribed.template_name = "task"
            return True

        async def mark_complete(cid):
            sample_capture_transcribed.status = "complete"
            sample_capture_transcribed.notion_page_id = "page-123"
            sample_capture_transcribed.notion_page_url = "https://notion.so/page-123"
            return True

        mock_db.update_status = AsyncMock(side_effect=track_status)
        mock_db.mark_complete = AsyncMock(side_effect=mark_complete)
        mock_db.get_capture_by_id = AsyncMock(return_value=sample_capture_transcribed)

        result = await orchestrator_with_classification.process_capture(
            sample_capture_transcribed.id
        )

        # Should complete successfully
        assert result.success is True

        # Classification should have been called
        mock_classification.classify.assert_called_once()

        # Notion should have been called
        mock_notion.create_capture_page.assert_called_once()
