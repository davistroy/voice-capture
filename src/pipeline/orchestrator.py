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
"""

import asyncio
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from src.db.database import Database
from src.db.models import CaptureRow
from src.models.capture import ProcessingStatus
from src.models.transcription import TranscriptionResult
from src.models.classification import ClassificationResult
from src.notion.client import NotionService, CaptureMetadata, NotionError
from src.pipeline.retry import RetryConfig
from src.transcription.service import TranscriptionService
from src.transcription.base import TranscriptionError, InvalidAudioError

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
    """

    success: bool
    capture_id: int
    notion_page_id: Optional[str] = None
    notion_page_url: Optional[str] = None
    error: Optional[str] = None
    stage: Optional[str] = None


class PipelineOrchestrator:
    """Coordinates the end-to-end processing pipeline.

    Manages state transitions through the state machine:
    pending -> transcribing -> classifying -> posting -> complete

    On error:
    - Increments retry_count
    - Logs error to failure_log
    - Stays in current state for retry

    After max retries:
    - Moves to failed state
    - Moves file to /failed/ directory

    Phase 1 behavior:
    - Skips classifying stage (uses generic template)
    - Direct path: pending -> transcribing -> posting -> complete

    Args:
        db: Database instance for state management.
        transcription: Transcription service instance.
        notion: Notion service instance.
        retry_config: Retry configuration (defaults to TDD spec).
        failed_path: Directory for failed files.
        classification: Optional classification service (Phase 2).
    """

    def __init__(
        self,
        db: Database,
        transcription: TranscriptionService,
        notion: NotionService,
        retry_config: Optional[RetryConfig] = None,
        failed_path: Optional[Path] = None,
        classification=None,  # Phase 2: ClassificationService
    ):
        self._db = db
        self._transcription = transcription
        self._notion = notion
        self._retry_config = retry_config or RetryConfig()
        self._failed_path = failed_path or Path("/app/failed")
        self._classification = classification  # None in Phase 1

    async def process_capture(self, capture_id: int) -> ProcessingResult:
        """Execute full pipeline for a single capture.

        State transitions (Phase 1, skipping classification):
            pending -> transcribing -> posting -> complete

        On error at any stage:
            - Increment retry_count
            - Log error to failure_log
            - Stay in current state

        After max retries:
            - Set status to failed
            - Move file to /failed/ directory
            - Log final failure

        Args:
            capture_id: ID of the capture to process.

        Returns:
            ProcessingResult indicating success/failure with details.
        """
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
            if capture.status in ("pending", "transcribing"):
                capture = await self._do_transcription(capture)
                if capture.status == "failed":
                    return self._failure_result(capture, ProcessingStage.TRANSCRIBING)

            # Stage 2: Classification (Phase 1: skip, use generic template)
            if capture.status == "classifying":
                capture = await self._do_classification(capture)
                if capture.status == "failed":
                    return self._failure_result(capture, ProcessingStage.CLASSIFYING)

            # Stage 3: Posting to Notion
            if capture.status == "posting":
                capture = await self._do_posting(capture)
                if capture.status == "failed":
                    return self._failure_result(capture, ProcessingStage.POSTING)

            # Success!
            if capture.status == "complete":
                return ProcessingResult(
                    success=True,
                    capture_id=capture_id,
                    notion_page_id=capture.notion_page_id,
                    notion_page_url=capture.notion_page_url,
                )

            # Unexpected state
            logger.warning(f"Capture {capture_id} in unexpected state: {capture.status}")
            return ProcessingResult(
                success=False,
                capture_id=capture_id,
                error=f"Unexpected state: {capture.status}",
            )

        except Exception as e:
            logger.exception(f"Unexpected error processing capture {capture_id}: {e}")
            return ProcessingResult(
                success=False,
                capture_id=capture_id,
                error=str(e),
            )

    async def _do_transcription(self, capture: CaptureRow) -> CaptureRow:
        """Perform transcription stage.

        Transitions: pending -> transcribing -> classifying (or posting in Phase 1)
        On error: increment retry, log failure, possibly move to failed

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

            # Update database with transcription result
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
                retryable=False,
            )

        except (TranscriptionError, FileNotFoundError) as e:
            # Transcription errors may be retryable
            retryable = getattr(e, "retryable", True)
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.TRANSCRIBING,
                error=e,
                retryable=retryable,
            )

        except Exception as e:
            # Unexpected errors are potentially retryable
            logger.exception(f"Unexpected transcription error for capture {capture_id}")
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.TRANSCRIBING,
                error=e,
                retryable=True,
            )

    async def _do_classification(self, capture: CaptureRow) -> CaptureRow:
        """Perform classification stage.

        Phase 1: This is a no-op, uses generic template.
        Phase 2: Will call classification service.

        Transitions: classifying -> posting

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
                title=self._generate_title_from_transcript(capture.transcript),
                tags=[],
            )

            await self._db.update_status(capture_id, "posting")
            logger.info(f"Capture {capture_id}: classification skipped (Phase 1), status -> posting")

            return await self._db.get_capture_by_id(capture_id)

        # Phase 2: Actual classification would go here
        try:
            # TODO: Phase 2 - call classification service
            # result = await self._classification.classify(capture.transcript, metadata)
            # await self._db.update_classification(...)
            pass

            await self._db.update_status(capture_id, "posting")
            return await self._db.get_capture_by_id(capture_id)

        except Exception as e:
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.CLASSIFYING,
                error=e,
                retryable=True,
            )

    async def _do_posting(self, capture: CaptureRow) -> CaptureRow:
        """Perform Notion posting stage.

        Transitions: posting -> complete
        On success: Delete source audio file

        Args:
            capture: The capture record to post.

        Returns:
            Updated capture record.
        """
        capture_id = capture.id

        try:
            # Build transcription result from stored data
            transcription = TranscriptionResult(
                text=capture.transcript or "",
                duration_seconds=capture.transcript_duration_seconds or 0.0,
                language=capture.transcript_language or "unknown",
            )

            # Build metadata
            metadata = CaptureMetadata(
                captured_at=capture.captured_at or datetime.utcnow(),
                device=self._format_device(capture.device),
                duration_seconds=capture.transcript_duration_seconds or 0.0,
            )

            # Generate title
            title = capture.suggested_title or self._generate_title_from_transcript(capture.transcript)

            # Create Notion page
            page = await self._notion.create_capture_page(
                transcription=transcription,
                metadata=metadata,
                title=title,
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
            await self._delete_source_file(capture)

            logger.info(
                f"Capture {capture_id}: posted to Notion, page_id={page.id}, status -> complete"
            )

            return await self._db.get_capture_by_id(capture_id)

        except NotionError as e:
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.POSTING,
                error=e,
                retryable=True,
            )

        except Exception as e:
            logger.exception(f"Unexpected posting error for capture {capture_id}")
            return await self._handle_failure(
                capture=capture,
                stage=ProcessingStage.POSTING,
                error=e,
                retryable=True,
            )

    async def _handle_failure(
        self,
        capture: CaptureRow,
        stage: ProcessingStage,
        error: Exception,
        retryable: bool,
    ) -> CaptureRow:
        """Handle a processing failure.

        If retryable and retries remaining:
            - Increment retry_count
            - Log error
            - Stay in current state

        If not retryable or retries exhausted:
            - Move to failed state
            - Move file to /failed/ directory

        Args:
            capture: The capture that failed.
            stage: The stage where failure occurred.
            error: The exception that was raised.
            retryable: Whether this error type is retryable.

        Returns:
            Updated capture record.
        """
        capture_id = capture.id
        error_message = str(error)
        error_type = type(error).__name__

        # Log the failure
        await self._db.log_failure(
            capture_id=capture_id,
            stage=stage.value,
            error_type=error_type,
            error_message=error_message,
            error_details={"retryable": retryable},
        )

        # Update last error
        await self._db.update_status(capture_id, capture.status, error=error_message)

        # Determine if we should retry
        current_retry_count = capture.retry_count
        can_retry = retryable and self._retry_config.should_retry(current_retry_count)

        if can_retry:
            # Increment retry count
            new_retry_count = await self._db.increment_retry(capture_id)
            logger.warning(
                f"Capture {capture_id}: {stage.value} failed (attempt {new_retry_count}/{self._retry_config.max_retries}), "
                f"will retry: {error_type}: {error_message}"
            )
        else:
            # Max retries exceeded or non-retryable - move to failed
            await self._db.update_status(capture_id, "failed", error=error_message)
            await self._move_to_failed(capture)
            logger.error(
                f"Capture {capture_id}: {stage.value} failed permanently after {current_retry_count} retries: "
                f"{error_type}: {error_message}"
            )

        return await self._db.get_capture_by_id(capture_id)

    async def _move_to_failed(self, capture: CaptureRow) -> None:
        """Move a capture's audio file to the failed directory.

        Args:
            capture: The capture whose file should be moved.
        """
        source_path = Path(capture.current_path or capture.original_path)

        if not source_path.exists():
            logger.warning(f"Cannot move file to failed - file not found: {source_path}")
            return

        # Ensure failed directory exists
        self._failed_path.mkdir(parents=True, exist_ok=True)

        # Move file
        dest_path = self._failed_path / source_path.name
        try:
            shutil.move(str(source_path), str(dest_path))
            await self._db.update_current_path(capture.id, str(dest_path))
            logger.info(f"Moved failed file to: {dest_path}")
        except Exception as e:
            logger.error(f"Failed to move file to {dest_path}: {e}")

    async def _delete_source_file(self, capture: CaptureRow) -> None:
        """Delete the source audio file after successful processing.

        Per PRD: Audio deleted on success - files removed from Google Drive
        after successful Notion post.

        Args:
            capture: The successfully processed capture.
        """
        file_path = Path(capture.current_path or capture.original_path)

        if not file_path.exists():
            logger.debug(f"Source file already deleted: {file_path}")
            return

        try:
            file_path.unlink()
            logger.info(f"Deleted source audio file: {file_path}")
        except Exception as e:
            # Non-fatal - log but don't fail the operation
            logger.warning(f"Failed to delete source file {file_path}: {e}")

    def _generate_title_from_transcript(self, transcript: Optional[str]) -> str:
        """Generate a title from the transcript text.

        Extracts the first sentence, limited to ~15 words.

        Args:
            transcript: The transcript text.

        Returns:
            A title string.
        """
        if not transcript:
            return "Voice Capture"

        # Find first sentence
        text = transcript.strip()
        for delimiter in [".", "!", "?"]:
            pos = text.find(delimiter)
            if pos != -1:
                text = text[: pos + 1]
                break

        # Limit to ~15 words
        words = text.split()
        if len(words) > 15:
            text = " ".join(words[:15]) + "..."

        return text or "Voice Capture"

    def _format_device(self, device: Optional[str]) -> str:
        """Format device string for display.

        Args:
            device: Raw device string (e.g., "watch", "phone").

        Returns:
            Formatted device name (e.g., "Watch", "Phone", "Unknown").
        """
        if not device:
            return "Unknown"

        device_lower = device.lower()
        if device_lower == "watch":
            return "Watch"
        elif device_lower == "phone":
            return "Phone"
        else:
            return "Unknown"

    def _failure_result(self, capture: CaptureRow, stage: ProcessingStage) -> ProcessingResult:
        """Create a ProcessingResult for a failed capture.

        Args:
            capture: The failed capture.
            stage: The stage where failure occurred.

        Returns:
            ProcessingResult indicating failure.
        """
        return ProcessingResult(
            success=False,
            capture_id=capture.id,
            error=capture.last_error,
            stage=stage.value,
        )

    async def process_pending_queue(self) -> list[ProcessingResult]:
        """Process all pending captures in the queue.

        Retrieves all captures with status='pending' and processes
        them sequentially. Per TDD: single-threaded sequential processing.

        Returns:
            List of ProcessingResult for each processed capture.
        """
        pending = await self._db.get_pending_captures()
        logger.info(f"Found {len(pending)} pending captures to process")

        results = []
        for capture in pending:
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

        # Reset capture
        await self._db.update_status(capture_id, target_status, error=None)

        # If file was moved to failed directory, we need to move it back
        if capture.current_path and self._failed_path in Path(capture.current_path).parents:
            logger.info(f"Note: File is in failed directory, manual file move may be required")

        logger.info(f"Retrying capture {capture_id} from {target_status}")

        return await self.process_capture(capture_id)
