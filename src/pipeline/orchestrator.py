"""Pipeline orchestrator for Voice Capture processing.

Coordinates the end-to-end pipeline from audio file to Notion page,
managing state transitions and error handling per TDD Section 5.1.

State Machine:
    pending -> transcribing -> classifying -> posting -> complete
                    |               |             |
                    v               v             v
                  (retry?)        (retry?)      (retry?)
                    |               |             |
                    v               v             v
                  failed          failed        failed

Work item 3.3 enhancements:
- Standardized retry config across all services
- Error categorization (retryable vs non-retryable)
- State preservation on retry (transcript not lost)
- Circuit breaker for sustained failures
- Improved error logging

Work item 6.9: Masks secrets in error messages and notifications.

Work item 6.8: Updated to use Protocol-based interfaces for loose coupling.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from src.common.secrets import mask_secrets
from src.db.database import Database
from src.db.models import CaptureRow
from src.models.capture import ProcessingStatus
from src.models.transcription import TranscriptionResult
from src.models.classification import ClassificationResult
from src.notion.client import CaptureMetadata, NotionError
from src.pipeline.retry import (
    RetryConfig,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    ErrorCategory,
    ErrorClassification,
    classify_error,
    build_detailed_error_log,
    PIPELINE_RETRY_CONFIG,
)
from src.pipeline.text_formatter import TextFormatter
from src.pipeline.file_operations import FileOperations
from src.transcription.base import TranscriptionError, InvalidAudioError

if TYPE_CHECKING:
    from src.classification import TemplateLoader
    from src.interfaces import (
        ITranscriptionService,
        IClassificationService,
        INotionService,
        INotificationService,
    )

logger = logging.getLogger(__name__)


class ProcessingStage(Enum):
    """Processing stages for error tracking."""

    TRANSCRIBING = "transcribing"
    CLASSIFYING = "classifying"
    POSTING = "posting"


@dataclass
class ProcessingResult:
    """Result from processing a capture.

    Attributes:
        success: Whether processing completed successfully.
        capture_id: The ID of the processed capture.
        notion_page_id: Notion page ID if created, None otherwise.
        notion_page_url: Notion page URL if created, None otherwise.
        error: Error message if failed, None otherwise.
        stage: Stage where failure occurred, None if successful.
        error_category: Category of error (retryable/non_retryable).
        circuit_open: Whether the circuit breaker is open.
    """

    success: bool
    capture_id: int
    notion_page_id: Optional[str] = None
    notion_page_url: Optional[str] = None
    template_name: Optional[str] = None
    error: Optional[str] = None
    stage: Optional[str] = None
    error_category: Optional[str] = None
    circuit_open: bool = False


class PipelineOrchestrator:
    """Coordinates the end-to-end processing pipeline.

    Manages state transitions through the state machine:
    pending -> transcribing -> classifying -> posting -> complete

    On error:
    - Classifies error as retryable or non-retryable
    - For retryable: increments retry_count, logs error, stays in current state
    - For non-retryable: moves to failed immediately
    - Preserves state on retry (e.g., transcript not lost)

    After max retries:
    - Moves to failed state
    - Moves file to /failed/ directory

    Circuit breaker:
    - Tracks consecutive failures across all captures
    - Opens after failure_threshold failures
    - Blocks new requests until recovery_timeout
    - Allows test request in half-open state

    Phase 1 behavior:
    - Skips classifying stage (uses generic template)
    - Direct path: pending -> transcribing -> posting -> complete

    Phase 2+ behavior:
    - Full pipeline with classification
    - Path: pending -> transcribing -> classifying -> posting -> complete
    - Uses ClassificationService to determine template and extract fields
    - Passes classification result and template to Notion for property mapping

    Notification integration (Phase 3+):
    - Sends failure notifications via Pushover after max retries exhausted
    - Includes filename, error message, and pipeline stage in notification
    - Includes Notion page URL if available (for partial failures)
    - Notifications are best-effort; failures don't affect processing

    Args:
        db: Database instance for state management.
        transcription: Transcription service instance.
        notion: Notion service instance.
        retry_config: Retry configuration (defaults to TDD spec).
        failed_path: Directory for failed files.
        classification: Optional classification service (Phase 2+).
        template_loader: Optional template loader for accessing templates (Phase 2+).
        notifications: Optional notification service (Phase 3+).
        file_operations: Optional FileOperations instance (created from failed_path if not provided).
    """

    def __init__(
        self,
        db: Database,
        transcription: "ITranscriptionService",
        notion: "INotionService",
        retry_config: Optional[RetryConfig] = None,
        failed_path: Optional[Path] = None,
        classification: Optional["IClassificationService"] = None,
        template_loader: Optional["TemplateLoader"] = None,
        notifications: Optional["INotificationService"] = None,
        file_operations: Optional[FileOperations] = None,
    ):
        self._db = db
        self._transcription = transcription
        self._notion = notion
        self._retry_config = retry_config or PIPELINE_RETRY_CONFIG
        self._classification = classification  # None in Phase 1
        self._template_loader = template_loader  # None in Phase 1
        self._notifications = notifications  # None if notifications disabled

        # Initialize file operations (work item 6.6: extracted helper class)
        self._failed_path = failed_path or Path("/app/failed")
        if file_operations is not None:
            self._file_ops = file_operations
        else:
            self._file_ops = FileOperations.from_failed_path(self._failed_path, db)

        # Track notified failures to prevent duplicate notifications
        self._notified_failures: set[int] = set()

        # Initialize circuit breaker if configured
        self._circuit_breaker: Optional[CircuitBreaker] = None
        if self._retry_config.circuit_breaker_config:
            self._circuit_breaker = CircuitBreaker(
                config=self._retry_config.circuit_breaker_config
            )

    async def process_capture(self, capture_id: int) -> ProcessingResult:
        """Execute full pipeline for a single capture.

        State transitions (Phase 1, skipping classification):
            pending -> transcribing -> posting -> complete

        State preservation on retry:
            - If capture already has transcript, skip transcription
            - If capture already has classification, skip classification
            - Retry from the stage where failure occurred

        On error at any stage:
            - Classify error as retryable or non-retryable
            - For retryable: increment retry_count, log error, stay in current state
            - For non-retryable: fail immediately

        After max retries:
            - Set status to failed
            - Move file to /failed/ directory
            - Log final failure

        Circuit breaker:
            - Check if circuit is open before processing
            - Record success/failure for circuit tracking

        Args:
            capture_id: ID of the capture to process.

        Returns:
            ProcessingResult indicating success/failure with details.
        """
        # Check circuit breaker
        if self._circuit_breaker and not self._circuit_breaker.should_allow_request():
            logger.warning(f"Circuit breaker open, rejecting capture {capture_id}")
            return ProcessingResult(
                success=False,
                capture_id=capture_id,
                error="Circuit breaker is open - service appears unavailable",
                circuit_open=True,
                error_category=ErrorCategory.RETRYABLE.value,
            )

        # Get capture record
        capture = await self._db.get_capture_by_id(capture_id)
        if not capture:
            logger.error(f"Capture not found: {capture_id}")
            return ProcessingResult(
                success=False,
                capture_id=capture_id,
                error="Capture not found",
            )

        logger.info(f"Processing capture {capture_id}: {capture.filename}, status={capture.status}")

        try:
            # Stage 1: Transcription
            # State preservation: Skip if transcript already exists
            if capture.status in ("pending", "transcribing"):
                if capture.transcript and len(capture.transcript) > 0:
                    # Transcript already exists from previous attempt, skip to next stage
                    logger.info(f"Capture {capture_id}: Using existing transcript (state preserved)")
                    if self._classification is None:
                        await self._db.update_status(capture_id, "posting")
                    else:
                        await self._db.update_status(capture_id, "classifying")
                    capture = await self._db.get_capture_by_id(capture_id)
                else:
                    capture = await self._do_transcription(capture)
                    if capture.status == "failed":
                        self._record_circuit_failure()
                        return self._failure_result(capture, ProcessingStage.TRANSCRIBING)

            # Stage 2: Classification (Phase 1: skip, use generic template)
            # State preservation: Skip if classification already exists
            if capture.status == "classifying":
                if capture.template_name and capture.classification_confidence is not None:
                    # Classification already exists, skip to posting
                    logger.info(f"Capture {capture_id}: Using existing classification (state preserved)")
                    await self._db.update_status(capture_id, "posting")
                    capture = await self._db.get_capture_by_id(capture_id)
                else:
                    capture = await self._do_classification(capture)
                    if capture.status == "failed":
                        self._record_circuit_failure()
                        return self._failure_result(capture, ProcessingStage.CLASSIFYING)

            # Stage 3: Posting to Notion
            if capture.status == "posting":
                capture = await self._do_posting(capture)
                if capture.status == "failed":
                    self._record_circuit_failure()
                    return self._failure_result(capture, ProcessingStage.POSTING)

            # Success!
            if capture.status == "complete":
                self._record_circuit_success()
                return ProcessingResult(
                    success=True,
                    capture_id=capture_id,
                    notion_page_id=capture.notion_page_id,
                    notion_page_url=capture.notion_page_url,
                    template_name=capture.template_name,
                )

            # Unexpected state
            logger.warning(f"Capture {capture_id} in unexpected state: {capture.status}")
            return ProcessingResult(
                success=False,
                capture_id=capture_id,
                error=f"Unexpected state: {capture.status}",
            )

        except CircuitOpenError as e:
            logger.warning(f"Circuit breaker triggered for capture {capture_id}")
            return ProcessingResult(
                success=False,
                capture_id=capture_id,
                error=str(e),
                circuit_open=True,
                error_category=ErrorCategory.RETRYABLE.value,
            )

        except Exception as e:
            logger.exception(f"Unexpected error processing capture {capture_id}: {e}")
            self._record_circuit_failure()
            return ProcessingResult(
                success=False,
                capture_id=capture_id,
                error=str(e),
            )

    def _record_circuit_success(self) -> None:
        """Record a successful operation for circuit breaker."""
        if self._circuit_breaker:
            self._circuit_breaker.record_success()

    def _record_circuit_failure(self) -> None:
        """Record a failed operation for circuit breaker."""
        if self._circuit_breaker:
            self._circuit_breaker.record_failure()

    async def _do_transcription(self, capture: CaptureRow) -> CaptureRow:
        """Perform transcription stage.

        Transitions: pending -> transcribing -> classifying (or posting in Phase 1)
        On error: classify error, increment retry if retryable, possibly fail

        State preservation: Stores transcript immediately on success so
        retry from classification stage uses same transcript.

        Args:
            capture: The capture record to transcribe.

        Returns:
            Updated capture record.
        """
        capture_id = capture.id

        # Transition to transcribing
        await self._db.update_status(capture_id, "transcribing")
        logger.debug(f"Capture {capture_id}: status -> transcribing")

        try:
            # Get file path
            file_path = Path(capture.current_path or capture.original_path)
            if not file_path.exists():
                raise FileNotFoundError(f"Audio file not found: {file_path}")

            # Transcribe
            result = await self._transcription.transcribe(file_path)

            # Update database with transcription result IMMEDIATELY
            # This ensures transcript is preserved if later stages fail
            await self._db.update_transcription(
                capture_id=capture_id,
                transcript=result.text,
                duration=result.duration_seconds,
                language=result.language,
            )

            # Phase 1: Skip classification, go directly to posting
            # Phase 2: Would transition to classifying
            if self._classification is None:
                next_status = "posting"
            else:
                next_status = "classifying"

            await self._db.update_status(capture_id, next_status)
            logger.info(
                f"Capture {capture_id}: transcription complete, "
                f"duration={result.duration_seconds:.1f}s, status -> {next_status}"
            )

            # Return updated capture
            return await self._db.get_capture_by_id(capture_id)

        except InvalidAudioError as e:
            # Invalid audio is non-retryable - fail immediately
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.TRANSCRIBING,
                error=e,
            )

        except (TranscriptionError, FileNotFoundError) as e:
            # Use error classification system
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.TRANSCRIBING,
                error=e,
            )

        except Exception as e:
            # Unexpected errors - classify and handle
            logger.exception(f"Unexpected transcription error for capture {capture_id}")
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.TRANSCRIBING,
                error=e,
            )

    async def _do_classification(self, capture: CaptureRow) -> CaptureRow:
        """Perform classification stage.

        Phase 1: This is a no-op, uses generic template.
        Phase 2+: Calls classification service to determine template and extract fields.

        Transitions: classifying -> posting

        State preservation: Uses transcript from capture record (not re-transcribing).
        Stores classification result immediately so posting retry uses same classification.

        Args:
            capture: The capture record to classify.

        Returns:
            Updated capture record.
        """
        capture_id = capture.id

        # Phase 1: Use generic template, skip classification
        if self._classification is None:
            # Set generic classification
            await self._db.update_classification(
                capture_id=capture_id,
                template="general",
                confidence=1.0,  # Always confident for generic
                fields={},
                title=TextFormatter.generate_title(capture.transcript),
                tags=[],
            )

            await self._db.update_status(capture_id, "posting")
            logger.info(f"Capture {capture_id}: classification skipped (Phase 1), status -> posting")

            return await self._db.get_capture_by_id(capture_id)

        # Phase 2+: Perform actual classification
        try:
            # Import here to avoid circular imports
            from src.classification.prompt_builder import TranscriptMetadata

            # Build metadata for classification
            # State preservation: Uses transcript from capture, not re-transcribing
            metadata = TranscriptMetadata(
                captured_at=capture.captured_at,
                duration_seconds=capture.transcript_duration_seconds,
                device=capture.device or "unknown",
            )

            # Call classification service
            result = await self._classification.classify(
                transcript=capture.transcript or "",
                metadata=metadata,
            )

            # Store classification result IMMEDIATELY in database
            # This ensures classification is preserved if posting fails
            await self._db.update_classification(
                capture_id=capture_id,
                template=result.template_name,
                confidence=result.confidence,
                fields=result.fields,
                title=result.title,
                tags=result.tags,
            )

            logger.info(
                f"Capture {capture_id}: classified as {result.template_name} "
                f"(confidence={result.confidence:.2f})"
            )

            # Transition to posting
            await self._db.update_status(capture_id, "posting")
            logger.debug(f"Capture {capture_id}: status -> posting")

            return await self._db.get_capture_by_id(capture_id)

        except Exception as e:
            # Classification errors - classify and handle
            logger.warning(f"Classification failed for capture {capture_id}: {e}")
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.CLASSIFYING,
                error=e,
            )

    async def _do_posting(self, capture: CaptureRow) -> CaptureRow:
        """Perform Notion posting stage.

        Transitions: posting -> complete
        On success: Delete source audio file

        Phase 1 behavior: Creates basic page with generic template.
        Phase 2+ behavior: Creates template-specific page with extracted fields.

        State preservation: Uses transcript and classification from capture record.

        Args:
            capture: The capture record to post.

        Returns:
            Updated capture record.
        """
        capture_id = capture.id

        try:
            # Build transcription result from stored data (state preservation)
            transcription = TranscriptionResult(
                text=capture.transcript or "",
                duration_seconds=capture.transcript_duration_seconds or 0.0,
                language=capture.transcript_language or "unknown",
            )

            # Build metadata
            metadata = CaptureMetadata(
                captured_at=capture.captured_at or datetime.utcnow(),
                device=TextFormatter.format_device_name(capture.device),
                duration_seconds=capture.transcript_duration_seconds or 0.0,
            )

            # Generate title
            title = capture.suggested_title or TextFormatter.generate_title(capture.transcript)

            # Build classification result if we have classification data (state preservation)
            classification = None
            template = None

            if capture.template_name and self._template_loader:
                # Build ClassificationResult from stored data
                import json
                classification = ClassificationResult(
                    template_name=capture.template_name,
                    confidence=capture.classification_confidence or 0.0,
                    fields=capture.extracted_fields or {},
                    title=capture.suggested_title or title,
                    tags=capture.tags or [],
                    reasoning=None,
                )

                # Get template configuration
                template = self._template_loader.get_template(capture.template_name)
                if not template:
                    logger.warning(
                        f"Template '{capture.template_name}' not found, "
                        f"falling back to basic page for capture {capture_id}"
                    )
                    classification = None

            # Create Notion page (with or without template-specific data)
            page = await self._notion.create_capture_page(
                transcription=transcription,
                metadata=metadata,
                title=title,
                classification=classification,
                template=template,
            )

            # Update database with Notion result
            await self._db.update_notion_result(
                capture_id=capture_id,
                page_id=page.id,
                page_url=page.url,
            )

            # Mark complete
            await self._db.mark_complete(capture_id)

            # Delete source audio file on success
            file_path = Path(capture.current_path or capture.original_path)
            await self._file_ops.delete_on_success(file_path)

            logger.info(
                f"Capture {capture_id}: posted to Notion, page_id={page.id}, status -> complete"
            )

            return await self._db.get_capture_by_id(capture_id)

        except NotionError as e:
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.POSTING,
                error=e,
            )

        except Exception as e:
            logger.exception(f"Unexpected posting error for capture {capture_id}")
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.POSTING,
                error=e,
            )

    async def _handle_failure(
        self,
        capture: CaptureRow,
        stage: ProcessingStage,
        error: Exception,
    ) -> CaptureRow:
        """Handle a processing failure with error classification.

        Uses classify_error to determine if error is retryable:
        - Retryable + retries remaining: increment retry_count, log, stay in state
        - Non-retryable OR retries exhausted: move to failed, move file

        Improved error logging per work item 3.3:
        - Logs detailed error information including category, retry_after hints
        - Includes traceback for debugging

        Args:
            capture: The capture that failed.
            stage: The stage where failure occurred.
            error: The exception that was raised.

        Returns:
            Updated capture record.
        """
        capture_id = capture.id

        # Classify the error to determine retry behavior
        classification = classify_error(error)
        is_retryable = classification.category == ErrorCategory.RETRYABLE

        # Build detailed error log for failure_log table
        error_details = build_detailed_error_log(
            capture_id=capture_id,
            stage=stage.value,
            error=error,
            retry_count=capture.retry_count,
            classification=classification,
        )

        # Log the failure with detailed information
        await self._db.log_failure(
            capture_id=capture_id,
            stage=stage.value,
            error_type=classification.error_type,
            error_message=classification.message,
            error_details=error_details,
        )

        # Update last error on capture
        await self._db.update_status(capture_id, capture.status, error=classification.message)

        # Determine if we should retry
        current_retry_count = capture.retry_count
        can_retry = is_retryable and self._retry_config.should_retry(current_retry_count)

        if can_retry:
            # Increment retry count
            new_retry_count = await self._db.increment_retry(capture_id)

            # Calculate backoff (respecting retry_after hint if present)
            backoff = self._retry_config.get_backoff(
                current_retry_count,
                retry_after=classification.retry_after,
            )

            logger.warning(
                f"Capture {capture_id}: {stage.value} failed "
                f"(attempt {new_retry_count}/{self._retry_config.max_retries}), "
                f"category={classification.category.value}, "
                f"will retry in {backoff:.1f}s: {classification.error_type}: {classification.message}"
            )
        else:
            # Max retries exceeded or non-retryable - move to failed
            reason = "non-retryable error" if not is_retryable else f"max retries ({self._retry_config.max_retries}) exceeded"
            await self._db.update_status(capture_id, "failed", error=classification.message)

            # Move file to failed directory
            source_path = Path(capture.current_path or capture.original_path)
            await self._file_ops.move_to_failed(source_path, capture_id)

            logger.error(
                f"Capture {capture_id}: {stage.value} failed permanently ({reason}): "
                f"category={classification.category.value}, "
                f"{classification.error_type}: {classification.message}"
            )

            # Send failure notification (Phase 3+)
            await self._send_failure_notification(
                capture=capture,
                stage=stage,
                error_message=classification.message,
            )

        return await self._db.get_capture_by_id(capture_id)

    async def _send_failure_notification(
        self,
        capture: CaptureRow,
        stage: ProcessingStage,
        error_message: str,
    ) -> None:
        """Send a failure notification via Pushover.

        Sends notification after max retries exhausted or non-retryable error.
        Includes relevant context: filename, error message, stage.
        Includes Notion page URL if available (for partial failures).

        Notifications are best-effort; failures don't affect pipeline operation.
        Tracks notified failures to prevent duplicate notifications for the same
        capture ID.

        Per work item 6.9: Masks any secrets that may appear in error messages
        before sending notifications.

        Args:
            capture: The capture that failed.
            stage: The pipeline stage where failure occurred.
            error_message: The error message to include in notification.
        """
        if not self._notifications:
            logger.debug(f"Notifications not configured, skipping failure notification for capture {capture.id}")
            return

        # Prevent duplicate notifications for the same failure
        if capture.id in self._notified_failures:
            logger.debug(f"Already notified for capture {capture.id}, skipping duplicate notification")
            return

        try:
            # Include Notion page URL if available (for partial failures where
            # page was created but something else failed)
            notion_page_url = capture.notion_page_url

            # Mask any secrets that may appear in the error message (defense-in-depth)
            masked_error_message = mask_secrets(error_message)

            success = await self._notifications.notify_processing_failure(
                filename=capture.filename,
                error_message=masked_error_message,
                stage=stage.value,
                notion_page_url=notion_page_url,
            )

            if success:
                # Track that we've notified for this capture
                self._notified_failures.add(capture.id)
                logger.info(f"Sent failure notification for capture {capture.id}")
            else:
                logger.warning(f"Failed to send notification for capture {capture.id}")

        except Exception as e:
            # Notification failures should not affect pipeline operation
            logger.error(f"Error sending failure notification for capture {capture.id}: {e}")

    def _failure_result(self, capture: CaptureRow, stage: ProcessingStage) -> ProcessingResult:
        """Create a ProcessingResult for a failed capture.

        Args:
            capture: The failed capture.
            stage: The stage where failure occurred.

        Returns:
            ProcessingResult indicating failure with error category.
        """
        # Classify the error to get category
        error_category = None
        if capture.last_error:
            # Try to determine category from the error message
            # In practice, the category was already determined in _handle_failure
            error_category = ErrorCategory.RETRYABLE.value  # Default

        return ProcessingResult(
            success=False,
            capture_id=capture.id,
            error=capture.last_error,
            stage=stage.value,
            error_category=error_category,
        )

    async def process_pending_queue(self) -> list[ProcessingResult]:
        """Process all pending captures in the queue.

        Retrieves all captures with status='pending' and processes
        them sequentially. Per TDD: single-threaded sequential processing.

        Applies backoff between retries based on retry count.
        Respects circuit breaker state.

        Returns:
            List of ProcessingResult for each processed capture.
        """
        pending = await self._db.get_pending_captures()
        logger.info(f"Found {len(pending)} pending captures to process")

        results = []
        for capture in pending:
            # Check circuit breaker before each capture
            if self._circuit_breaker and self._circuit_breaker.is_open:
                logger.warning(f"Circuit breaker open, skipping capture {capture.id}")
                results.append(ProcessingResult(
                    success=False,
                    capture_id=capture.id,
                    error="Circuit breaker is open",
                    circuit_open=True,
                ))
                continue

            # Apply backoff between retries if capture has failed before
            if capture.retry_count > 0:
                backoff = self._retry_config.get_backoff(capture.retry_count - 1)
                logger.debug(f"Capture {capture.id}: waiting {backoff:.1f}s (retry backoff)")
                await asyncio.sleep(backoff)

            result = await self.process_capture(capture.id)
            results.append(result)

            # Log progress
            status = "SUCCESS" if result.success else "FAILED"
            logger.info(f"Processed capture {capture.id}: {status}")

        return results

    async def retry_failed(
        self,
        capture_id: int,
        from_stage: Optional[str] = None,
    ) -> ProcessingResult:
        """Manually retry a failed capture.

        Resets the capture to pending (or specified stage) and reprocesses.
        Preserves existing transcript and classification if retrying from later stage.

        Args:
            capture_id: ID of the capture to retry.
            from_stage: Optional stage to restart from ("transcribing", "classifying", "posting").
                       If None, resets to pending.

        Returns:
            ProcessingResult from reprocessing.
        """
        capture = await self._db.get_capture_by_id(capture_id)
        if not capture:
            return ProcessingResult(
                success=False,
                capture_id=capture_id,
                error="Capture not found",
            )

        if capture.status != "failed":
            logger.warning(f"Capture {capture_id} is not in failed state: {capture.status}")

        # Determine target status
        if from_stage and from_stage in ("transcribing", "classifying", "posting"):
            target_status = from_stage
        else:
            target_status = "pending"

        # Log what state will be preserved
        if target_status == "classifying" and capture.transcript:
            logger.info(f"Capture {capture_id}: retrying from classifying, preserving transcript")
        elif target_status == "posting" and capture.template_name:
            logger.info(f"Capture {capture_id}: retrying from posting, preserving transcript and classification")

        # Reset capture status (error cleared, but don't reset retry_count for manual retries)
        await self._db.update_status(capture_id, target_status, error=None)

        # Clear notification tracking to allow re-notification if retry fails
        self.clear_notification_tracking(capture_id)

        # If file was moved to failed directory, we need to move it back
        if capture.current_path and self._file_ops.is_in_failed_directory(Path(capture.current_path)):
            logger.info(f"Note: File is in failed directory, manual file move may be required")

        logger.info(f"Retrying capture {capture_id} from {target_status}")

        return await self.process_capture(capture_id)

    def get_circuit_breaker_status(self) -> Optional[dict]:
        """Get current circuit breaker status.

        Returns:
            Dict with circuit breaker state, or None if not configured.
        """
        if self._circuit_breaker:
            return self._circuit_breaker.get_status()
        return None

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker to closed state.

        Useful for recovery after fixing underlying service issues.
        """
        if self._circuit_breaker:
            self._circuit_breaker.reset()
            logger.info("Circuit breaker manually reset to closed state")

    def clear_notification_tracking(self, capture_id: Optional[int] = None) -> None:
        """Clear the notified failures tracking.

        Useful for manual retries where we want to allow re-notification
        if the retry also fails.

        Args:
            capture_id: Specific capture ID to clear. If None, clears all.
        """
        if capture_id is not None:
            self._notified_failures.discard(capture_id)
            logger.debug(f"Cleared notification tracking for capture {capture_id}")
        else:
            self._notified_failures.clear()
            logger.debug("Cleared all notification tracking")
