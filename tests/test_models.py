"""
Unit tests for domain models.

Tests cover:
- ProcessingStatus enum and state transitions
- Device enum and string conversion
- TranscriptionResult dataclass and serialization
- ClassificationResult dataclass and serialization
- CaptureRecord dataclass, validation, and database serialization
"""

import json
import pytest
from datetime import datetime

from src.models import (
    ProcessingStatus,
    Device,
    TranscriptionResult,
    ClassificationResult,
    CaptureRecord,
)


class TestProcessingStatus:
    """Tests for ProcessingStatus enum."""

    def test_enum_values(self):
        """All expected states exist with correct string values."""
        assert ProcessingStatus.PENDING.value == "pending"
        assert ProcessingStatus.TRANSCRIBING.value == "transcribing"
        assert ProcessingStatus.CLASSIFYING.value == "classifying"
        assert ProcessingStatus.POSTING.value == "posting"
        assert ProcessingStatus.COMPLETE.value == "complete"
        assert ProcessingStatus.FAILED.value == "failed"

    def test_from_string_valid(self):
        """from_string creates correct enum from valid strings."""
        assert ProcessingStatus.from_string("pending") == ProcessingStatus.PENDING
        assert ProcessingStatus.from_string("PENDING") == ProcessingStatus.PENDING
        assert ProcessingStatus.from_string("Pending") == ProcessingStatus.PENDING
        assert ProcessingStatus.from_string("transcribing") == ProcessingStatus.TRANSCRIBING
        assert ProcessingStatus.from_string("complete") == ProcessingStatus.COMPLETE

    def test_from_string_invalid(self):
        """from_string raises ValueError for invalid strings."""
        with pytest.raises(ValueError, match="Invalid processing status"):
            ProcessingStatus.from_string("invalid")
        with pytest.raises(ValueError):
            ProcessingStatus.from_string("")

    def test_valid_transitions_from_pending(self):
        """PENDING can only transition to TRANSCRIBING."""
        assert ProcessingStatus.PENDING.can_transition_to(ProcessingStatus.TRANSCRIBING)
        assert not ProcessingStatus.PENDING.can_transition_to(ProcessingStatus.CLASSIFYING)
        assert not ProcessingStatus.PENDING.can_transition_to(ProcessingStatus.COMPLETE)
        assert not ProcessingStatus.PENDING.can_transition_to(ProcessingStatus.FAILED)

    def test_valid_transitions_from_transcribing(self):
        """TRANSCRIBING can transition to CLASSIFYING or FAILED."""
        assert ProcessingStatus.TRANSCRIBING.can_transition_to(ProcessingStatus.CLASSIFYING)
        assert ProcessingStatus.TRANSCRIBING.can_transition_to(ProcessingStatus.FAILED)
        assert not ProcessingStatus.TRANSCRIBING.can_transition_to(ProcessingStatus.POSTING)
        assert not ProcessingStatus.TRANSCRIBING.can_transition_to(ProcessingStatus.COMPLETE)

    def test_valid_transitions_from_classifying(self):
        """CLASSIFYING can transition to POSTING or FAILED."""
        assert ProcessingStatus.CLASSIFYING.can_transition_to(ProcessingStatus.POSTING)
        assert ProcessingStatus.CLASSIFYING.can_transition_to(ProcessingStatus.FAILED)
        assert not ProcessingStatus.CLASSIFYING.can_transition_to(ProcessingStatus.COMPLETE)

    def test_valid_transitions_from_posting(self):
        """POSTING can transition to COMPLETE or FAILED."""
        assert ProcessingStatus.POSTING.can_transition_to(ProcessingStatus.COMPLETE)
        assert ProcessingStatus.POSTING.can_transition_to(ProcessingStatus.FAILED)
        assert not ProcessingStatus.POSTING.can_transition_to(ProcessingStatus.CLASSIFYING)

    def test_complete_is_terminal(self):
        """COMPLETE cannot transition to any state."""
        assert not ProcessingStatus.COMPLETE.can_transition_to(ProcessingStatus.PENDING)
        assert not ProcessingStatus.COMPLETE.can_transition_to(ProcessingStatus.FAILED)

    def test_failed_can_retry(self):
        """FAILED can transition back to PENDING for retry."""
        assert ProcessingStatus.FAILED.can_transition_to(ProcessingStatus.PENDING)
        assert not ProcessingStatus.FAILED.can_transition_to(ProcessingStatus.TRANSCRIBING)


class TestDevice:
    """Tests for Device enum."""

    def test_enum_values(self):
        """All expected devices exist with correct string values."""
        assert Device.WATCH.value == "watch"
        assert Device.PHONE.value == "phone"
        assert Device.UNKNOWN.value == "unknown"

    def test_from_string_valid(self):
        """from_string creates correct enum from valid strings."""
        assert Device.from_string("watch") == Device.WATCH
        assert Device.from_string("WATCH") == Device.WATCH
        assert Device.from_string("Watch") == Device.WATCH
        assert Device.from_string("phone") == Device.PHONE

    def test_from_string_unknown_returns_unknown(self):
        """from_string returns UNKNOWN for unrecognized values."""
        assert Device.from_string("invalid") == Device.UNKNOWN
        assert Device.from_string("") == Device.UNKNOWN
        assert Device.from_string("tablet") == Device.UNKNOWN


class TestTranscriptionResult:
    """Tests for TranscriptionResult dataclass."""

    def test_basic_creation(self):
        """Create TranscriptionResult with required fields."""
        result = TranscriptionResult(
            text="Hello world",
            duration_seconds=5.5,
            language="en",
        )
        assert result.text == "Hello world"
        assert result.duration_seconds == 5.5
        assert result.language == "en"
        assert result.segments is None

    def test_creation_with_segments(self):
        """Create TranscriptionResult with segments."""
        segments = [
            {"start": 0.0, "end": 2.5, "text": "Hello"},
            {"start": 2.5, "end": 5.5, "text": "world"},
        ]
        result = TranscriptionResult(
            text="Hello world",
            duration_seconds=5.5,
            language="en",
            segments=segments,
        )
        assert result.segments == segments

    def test_validation_text_type(self):
        """Validation fails for non-string text."""
        with pytest.raises(ValueError, match="text must be a string"):
            TranscriptionResult(text=123, duration_seconds=5.0, language="en")

    def test_validation_negative_duration(self):
        """Validation fails for negative duration."""
        with pytest.raises(ValueError, match="duration_seconds cannot be negative"):
            TranscriptionResult(text="test", duration_seconds=-1.0, language="en")

    def test_validation_duration_type(self):
        """Validation fails for non-numeric duration."""
        with pytest.raises(ValueError, match="duration_seconds must be a number"):
            TranscriptionResult(text="test", duration_seconds="five", language="en")

    def test_to_dict(self):
        """to_dict returns complete dictionary."""
        result = TranscriptionResult(
            text="Test transcript",
            duration_seconds=10.5,
            language="en",
            segments=[{"start": 0, "end": 10.5, "text": "Test transcript"}],
        )
        d = result.to_dict()
        assert d["text"] == "Test transcript"
        assert d["duration_seconds"] == 10.5
        assert d["language"] == "en"
        assert len(d["segments"]) == 1

    def test_to_json_from_json_roundtrip(self):
        """JSON serialization roundtrip preserves data."""
        original = TranscriptionResult(
            text="Test transcript",
            duration_seconds=10.5,
            language="en",
            segments=[{"start": 0, "end": 10.5, "text": "Test transcript"}],
        )
        json_str = original.to_json()
        restored = TranscriptionResult.from_json(json_str)
        assert restored.text == original.text
        assert restored.duration_seconds == original.duration_seconds
        assert restored.language == original.language
        assert restored.segments == original.segments

    def test_from_whisper_response(self):
        """from_whisper_response parses API response correctly."""
        response = {
            "task": "transcribe",
            "language": "english",
            "duration": 45.2,
            "text": "Full transcript text here...",
            "segments": [
                {"id": 0, "start": 0.0, "end": 5.2, "text": "First segment"},
            ],
        }
        result = TranscriptionResult.from_whisper_response(response)
        assert result.text == "Full transcript text here..."
        assert result.duration_seconds == 45.2
        assert result.language == "english"
        assert len(result.segments) == 1

    def test_get_word_count(self):
        """get_word_count returns correct count."""
        result = TranscriptionResult(
            text="This is a test with seven words",
            duration_seconds=5.0,
            language="en",
        )
        assert result.get_word_count() == 7

    def test_get_first_sentence_with_period(self):
        """get_first_sentence extracts first sentence ending in period."""
        result = TranscriptionResult(
            text="First sentence here. Second sentence follows. Third one too.",
            duration_seconds=10.0,
            language="en",
        )
        assert result.get_first_sentence() == "First sentence here."

    def test_get_first_sentence_truncation(self):
        """get_first_sentence truncates long sentences."""
        long_text = " ".join(["word"] * 30)
        result = TranscriptionResult(text=long_text, duration_seconds=60.0, language="en")
        first = result.get_first_sentence(max_words=10)
        assert "..." in first
        assert len(first.split()) <= 11  # 10 words + "..."


class TestClassificationResult:
    """Tests for ClassificationResult dataclass."""

    def test_basic_creation(self):
        """Create ClassificationResult with required fields."""
        result = ClassificationResult(
            template_name="task",
            confidence=0.85,
            fields={"priority": "High"},
            title="Review the quarterly report",
            tags=["work", "review"],
        )
        assert result.template_name == "task"
        assert result.confidence == 0.85
        assert result.fields == {"priority": "High"}
        assert result.title == "Review the quarterly report"
        assert result.tags == ["work", "review"]
        assert result.reasoning is None

    def test_creation_with_reasoning(self):
        """Create ClassificationResult with optional reasoning."""
        result = ClassificationResult(
            template_name="task",
            confidence=0.85,
            fields={},
            title="Test",
            tags=[],
            reasoning="This is clearly a task due to imperative language.",
        )
        assert result.reasoning == "This is clearly a task due to imperative language."

    def test_validation_empty_template_name(self):
        """Validation fails for empty template_name."""
        with pytest.raises(ValueError, match="template_name must be a non-empty string"):
            ClassificationResult(
                template_name="",
                confidence=0.5,
                fields={},
                title="Test",
                tags=[],
            )

    def test_validation_confidence_range(self):
        """Validation fails for confidence outside 0.0-1.0."""
        with pytest.raises(ValueError, match="confidence must be between"):
            ClassificationResult(
                template_name="task",
                confidence=1.5,
                fields={},
                title="Test",
                tags=[],
            )
        with pytest.raises(ValueError, match="confidence must be between"):
            ClassificationResult(
                template_name="task",
                confidence=-0.1,
                fields={},
                title="Test",
                tags=[],
            )

    def test_validation_tags_type(self):
        """Validation fails for non-list tags."""
        with pytest.raises(ValueError, match="tags must be a list"):
            ClassificationResult(
                template_name="task",
                confidence=0.5,
                fields={},
                title="Test",
                tags="not-a-list",
            )

    def test_validation_tags_contents(self):
        """Validation fails for non-string tags."""
        with pytest.raises(ValueError, match="all tags must be strings"):
            ClassificationResult(
                template_name="task",
                confidence=0.5,
                fields={},
                title="Test",
                tags=["valid", 123, "also-valid"],
            )

    def test_to_dict_from_dict_roundtrip(self):
        """Dictionary serialization roundtrip preserves data."""
        original = ClassificationResult(
            template_name="journal",
            confidence=0.92,
            fields={"mood": "Productive", "summary": "Great day"},
            title="Productive day at work",
            tags=["work", "mood"],
            reasoning="Clear personal reflection",
        )
        d = original.to_dict()
        restored = ClassificationResult.from_dict(d)
        assert restored.template_name == original.template_name
        assert restored.confidence == original.confidence
        assert restored.fields == original.fields
        assert restored.title == original.title
        assert restored.tags == original.tags
        assert restored.reasoning == original.reasoning

    def test_from_llm_response(self):
        """from_llm_response parses Claude API response correctly."""
        response = {
            "template": "task",
            "confidence": 0.87,
            "reasoning": "Contains imperative language",
            "title": "Review quarterly report",
            "tags": ["work", "review"],
            "fields": {"priority": "High", "due_date": "2026-01-25"},
        }
        result = ClassificationResult.from_llm_response(response)
        assert result.template_name == "task"
        assert result.confidence == 0.87
        assert result.reasoning == "Contains imperative language"
        assert result.title == "Review quarterly report"
        assert result.tags == ["work", "review"]
        assert result.fields["priority"] == "High"

    def test_is_above_threshold(self):
        """is_above_threshold checks confidence correctly."""
        result = ClassificationResult(
            template_name="task",
            confidence=0.75,
            fields={},
            title="Test",
            tags=[],
        )
        assert result.is_above_threshold(0.7)
        assert result.is_above_threshold(0.75)
        assert not result.is_above_threshold(0.8)

    def test_is_fallback(self):
        """is_fallback detects general template."""
        general = ClassificationResult(
            template_name="general",
            confidence=0.5,
            fields={},
            title="Test",
            tags=[],
        )
        task = ClassificationResult(
            template_name="task",
            confidence=0.9,
            fields={},
            title="Test",
            tags=[],
        )
        assert general.is_fallback()
        assert not task.is_fallback()

    def test_get_field(self):
        """get_field retrieves fields with default."""
        result = ClassificationResult(
            template_name="task",
            confidence=0.8,
            fields={"priority": "High", "context": "Work project"},
            title="Test",
            tags=[],
        )
        assert result.get_field("priority") == "High"
        assert result.get_field("missing") is None
        assert result.get_field("missing", "default") == "default"

    def test_create_fallback(self):
        """create_fallback produces valid general classification."""
        fallback = ClassificationResult.create_fallback(
            title="Untitled capture",
            transcript_text="Some transcript content",
            tags=["misc"],
        )
        assert fallback.template_name == "general"
        assert fallback.confidence == 0.0
        assert fallback.title == "Untitled capture"
        assert "misc" in fallback.tags
        assert fallback.is_fallback()


class TestCaptureRecord:
    """Tests for CaptureRecord dataclass."""

    def test_default_creation(self):
        """Create CaptureRecord with defaults."""
        record = CaptureRecord()
        assert record.id is None
        assert record.filename == ""
        assert record.status == ProcessingStatus.PENDING
        assert record.device == Device.UNKNOWN
        assert record.retry_count == 0
        assert record.transcription is None
        assert record.classification is None

    def test_creation_with_values(self):
        """Create CaptureRecord with specific values."""
        now = datetime.now()
        record = CaptureRecord(
            id=42,
            filename="2026-01-20T143022_watch.m4a",
            original_path="/inbox/2026-01-20T143022_watch.m4a",
            current_path="/processing/2026-01-20T143022_watch.m4a",
            device=Device.WATCH,
            captured_at=now,
            status=ProcessingStatus.TRANSCRIBING,
            retry_count=1,
        )
        assert record.id == 42
        assert record.filename == "2026-01-20T143022_watch.m4a"
        assert record.device == Device.WATCH
        assert record.status == ProcessingStatus.TRANSCRIBING
        assert record.retry_count == 1

    def test_string_enum_conversion(self):
        """Enums can be passed as strings and are converted."""
        record = CaptureRecord(
            filename="test.m4a",
            device="watch",
            status="transcribing",
        )
        assert record.device == Device.WATCH
        assert record.status == ProcessingStatus.TRANSCRIBING

    def test_validation_negative_retry_count(self):
        """Validation fails for negative retry_count."""
        with pytest.raises(ValueError, match="retry_count cannot be negative"):
            CaptureRecord(filename="test.m4a", retry_count=-1)

    def test_to_dict_basic(self):
        """to_dict produces complete dictionary with None values."""
        record = CaptureRecord(
            filename="test.m4a",
            device=Device.WATCH,
            status=ProcessingStatus.PENDING,
        )
        d = record.to_dict()
        assert d["filename"] == "test.m4a"
        assert d["device"] == "watch"
        assert d["status"] == "pending"
        assert d["transcription"] is None
        assert d["classification"] is None

    def test_to_dict_with_nested_models(self):
        """to_dict includes nested transcription and classification."""
        transcription = TranscriptionResult(
            text="Test transcript",
            duration_seconds=10.0,
            language="en",
        )
        classification = ClassificationResult(
            template_name="task",
            confidence=0.9,
            fields={"priority": "High"},
            title="Test task",
            tags=["test"],
        )
        record = CaptureRecord(
            filename="test.m4a",
            transcription=transcription,
            classification=classification,
        )
        d = record.to_dict()
        assert d["transcription"]["text"] == "Test transcript"
        assert d["classification"]["template_name"] == "task"

    def test_to_json_from_json_roundtrip(self):
        """JSON serialization roundtrip preserves all data."""
        now = datetime(2026, 1, 20, 14, 30, 22)
        transcription = TranscriptionResult(
            text="Test transcript",
            duration_seconds=10.0,
            language="en",
        )
        classification = ClassificationResult(
            template_name="task",
            confidence=0.9,
            fields={"priority": "High"},
            title="Test task",
            tags=["test"],
        )
        original = CaptureRecord(
            id=42,
            filename="test.m4a",
            original_path="/inbox/test.m4a",
            device=Device.WATCH,
            captured_at=now,
            status=ProcessingStatus.COMPLETE,
            transcription=transcription,
            classification=classification,
            notion_page_id="page123",
            notion_page_url="https://notion.so/page123",
            created_at=now,
            completed_at=now,
        )
        json_str = original.to_json()
        restored = CaptureRecord.from_json(json_str)

        assert restored.id == original.id
        assert restored.filename == original.filename
        assert restored.device == original.device
        assert restored.status == original.status
        assert restored.captured_at == original.captured_at
        assert restored.transcription.text == original.transcription.text
        assert restored.classification.template_name == original.classification.template_name
        assert restored.notion_page_id == original.notion_page_id

    def test_from_db_row(self):
        """from_db_row creates record from flattened database row."""
        row = {
            "id": 42,
            "filename": "test.m4a",
            "original_path": "/inbox/test.m4a",
            "current_path": "/processing/test.m4a",
            "device": "watch",
            "captured_at": "2026-01-20T14:30:22",
            "status": "complete",
            "retry_count": 0,
            "last_error": None,
            "last_attempt_at": None,
            "transcript": "Test transcript content",
            "transcript_duration_seconds": 15.5,
            "transcript_language": "en",
            "template_name": "task",
            "classification_confidence": 0.92,
            "extracted_fields": '{"priority": "High"}',
            "suggested_title": "Test task",
            "tags": '["work", "test"]',
            "notion_page_id": "page123",
            "notion_page_url": "https://notion.so/page123",
            "created_at": "2026-01-20T14:30:00",
            "updated_at": "2026-01-20T14:30:30",
            "completed_at": "2026-01-20T14:30:30",
        }
        record = CaptureRecord.from_db_row(row)

        assert record.id == 42
        assert record.filename == "test.m4a"
        assert record.device == Device.WATCH
        assert record.status == ProcessingStatus.COMPLETE
        assert record.transcription is not None
        assert record.transcription.text == "Test transcript content"
        assert record.transcription.duration_seconds == 15.5
        assert record.classification is not None
        assert record.classification.template_name == "task"
        assert record.classification.confidence == 0.92
        assert record.classification.fields == {"priority": "High"}
        assert record.classification.tags == ["work", "test"]

    def test_from_db_row_without_transcription(self):
        """from_db_row handles rows without transcription."""
        row = {
            "id": 1,
            "filename": "test.m4a",
            "original_path": "/inbox/test.m4a",
            "device": "phone",
            "status": "pending",
            "retry_count": 0,
            "transcript": None,
            "template_name": None,
        }
        record = CaptureRecord.from_db_row(row)
        assert record.transcription is None
        assert record.classification is None

    def test_to_db_dict(self):
        """to_db_dict produces flattened database format."""
        transcription = TranscriptionResult(
            text="Test transcript",
            duration_seconds=10.0,
            language="en",
        )
        classification = ClassificationResult(
            template_name="task",
            confidence=0.9,
            fields={"priority": "High"},
            title="Test task",
            tags=["test"],
        )
        record = CaptureRecord(
            id=42,
            filename="test.m4a",
            original_path="/inbox/test.m4a",
            device=Device.WATCH,
            status=ProcessingStatus.COMPLETE,
            transcription=transcription,
            classification=classification,
        )
        d = record.to_db_dict()

        assert d["id"] == 42
        assert d["filename"] == "test.m4a"
        assert d["device"] == "watch"
        assert d["status"] == "complete"
        # Flattened transcription
        assert d["transcript"] == "Test transcript"
        assert d["transcript_duration_seconds"] == 10.0
        assert d["transcript_language"] == "en"
        # Flattened classification
        assert d["template_name"] == "task"
        assert d["classification_confidence"] == 0.9
        assert json.loads(d["extracted_fields"]) == {"priority": "High"}
        assert d["suggested_title"] == "Test task"
        assert json.loads(d["tags"]) == ["test"]

    def test_to_db_dict_without_nested_models(self):
        """to_db_dict handles records without transcription/classification."""
        record = CaptureRecord(
            filename="test.m4a",
            original_path="/inbox/test.m4a",
            device=Device.PHONE,
            status=ProcessingStatus.PENDING,
        )
        d = record.to_db_dict()

        assert d["transcript"] is None
        assert d["transcript_duration_seconds"] is None
        assert d["template_name"] is None
        assert d["classification_confidence"] is None
        assert "id" not in d  # id=None should not be included

    def test_is_terminal(self):
        """is_terminal identifies COMPLETE and FAILED as terminal."""
        complete = CaptureRecord(status=ProcessingStatus.COMPLETE)
        failed = CaptureRecord(status=ProcessingStatus.FAILED)
        pending = CaptureRecord(status=ProcessingStatus.PENDING)
        transcribing = CaptureRecord(status=ProcessingStatus.TRANSCRIBING)

        assert complete.is_terminal()
        assert failed.is_terminal()
        assert not pending.is_terminal()
        assert not transcribing.is_terminal()

    def test_is_retryable(self):
        """is_retryable checks status and retry_count."""
        # Failed with retries remaining
        failed_0 = CaptureRecord(status=ProcessingStatus.FAILED, retry_count=0)
        failed_2 = CaptureRecord(status=ProcessingStatus.FAILED, retry_count=2)
        failed_3 = CaptureRecord(status=ProcessingStatus.FAILED, retry_count=3)

        assert failed_0.is_retryable(max_retries=3)
        assert failed_2.is_retryable(max_retries=3)
        assert not failed_3.is_retryable(max_retries=3)

        # Non-failed status
        pending = CaptureRecord(status=ProcessingStatus.PENDING, retry_count=0)
        assert not pending.is_retryable(max_retries=3)

    def test_get_duration_seconds(self):
        """get_duration_seconds returns transcription duration."""
        with_transcription = CaptureRecord(
            transcription=TranscriptionResult(
                text="test",
                duration_seconds=25.5,
                language="en",
            )
        )
        without_transcription = CaptureRecord()

        assert with_transcription.get_duration_seconds() == 25.5
        assert without_transcription.get_duration_seconds() is None

    def test_get_template_name(self):
        """get_template_name returns classification template."""
        with_classification = CaptureRecord(
            classification=ClassificationResult(
                template_name="journal",
                confidence=0.8,
                fields={},
                title="Test",
                tags=[],
            )
        )
        without_classification = CaptureRecord()

        assert with_classification.get_template_name() == "journal"
        assert without_classification.get_template_name() is None

    def test_get_title_priority(self):
        """get_title returns best available title in priority order."""
        # Classification title takes priority
        record_with_all = CaptureRecord(
            filename="test.m4a",
            transcription=TranscriptionResult(
                text="This is the transcript text.",
                duration_seconds=5.0,
                language="en",
            ),
            classification=ClassificationResult(
                template_name="task",
                confidence=0.9,
                fields={},
                title="Classification Title",
                tags=[],
            ),
        )
        assert record_with_all.get_title() == "Classification Title"

        # Falls back to transcript first sentence
        record_with_transcript = CaptureRecord(
            filename="test.m4a",
            transcription=TranscriptionResult(
                text="This is the transcript text. More content here.",
                duration_seconds=5.0,
                language="en",
            ),
        )
        assert record_with_transcript.get_title() == "This is the transcript text."

        # Falls back to filename
        record_minimal = CaptureRecord(filename="2026-01-20_watch.m4a")
        assert record_minimal.get_title() == "2026-01-20_watch.m4a"


class TestIntegration:
    """Integration tests for model interactions."""

    def test_full_capture_lifecycle(self):
        """Test a capture through its full lifecycle."""
        # 1. Initial capture detection
        record = CaptureRecord(
            filename="2026-01-20T143022_watch.m4a",
            original_path="/inbox/2026-01-20T143022_watch.m4a",
            device=Device.WATCH,
            captured_at=datetime(2026, 1, 20, 14, 30, 22),
            status=ProcessingStatus.PENDING,
            created_at=datetime.now(),
        )

        # 2. Transcription complete
        record.transcription = TranscriptionResult(
            text="I need to review the quarterly report by Friday. It's important for the board meeting.",
            duration_seconds=8.5,
            language="en",
        )
        record.status = ProcessingStatus.CLASSIFYING

        # 3. Classification complete
        record.classification = ClassificationResult(
            template_name="task",
            confidence=0.92,
            fields={"priority": "High", "due_date": "2026-01-24"},
            title="Review quarterly report by Friday",
            tags=["work", "quarterly-review", "board-meeting"],
            reasoning="Clear task with deadline",
        )
        record.status = ProcessingStatus.POSTING

        # 4. Notion post complete
        record.notion_page_id = "abc123"
        record.notion_page_url = "https://notion.so/abc123"
        record.status = ProcessingStatus.COMPLETE
        record.completed_at = datetime.now()

        # Verify final state
        assert record.is_terminal()
        assert record.get_template_name() == "task"
        assert record.get_duration_seconds() == 8.5
        assert record.get_title() == "Review quarterly report by Friday"
        assert record.classification.is_above_threshold(0.7)

        # Verify serialization
        json_str = record.to_json()
        restored = CaptureRecord.from_json(json_str)
        assert restored.status == ProcessingStatus.COMPLETE
        assert restored.transcription.text == record.transcription.text
        assert restored.classification.template_name == "task"

    def test_db_roundtrip(self):
        """Test database serialization roundtrip."""
        now = datetime(2026, 1, 20, 14, 30, 22)
        original = CaptureRecord(
            id=42,
            filename="test.m4a",
            original_path="/inbox/test.m4a",
            current_path="/processing/test.m4a",
            device=Device.WATCH,
            captured_at=now,
            status=ProcessingStatus.COMPLETE,
            retry_count=1,
            transcription=TranscriptionResult(
                text="Test transcript",
                duration_seconds=10.5,
                language="en",
            ),
            classification=ClassificationResult(
                template_name="journal",
                confidence=0.85,
                fields={"mood": "Productive"},
                title="Journal entry",
                tags=["daily", "work"],
            ),
            notion_page_id="page123",
            notion_page_url="https://notion.so/page123",
            created_at=now,
            updated_at=now,
            completed_at=now,
        )

        # Simulate DB write
        db_dict = original.to_db_dict()

        # Simulate DB read
        restored = CaptureRecord.from_db_row(db_dict)

        # Verify all fields preserved
        assert restored.id == original.id
        assert restored.filename == original.filename
        assert restored.device == original.device
        assert restored.status == original.status
        assert restored.transcription.text == original.transcription.text
        assert restored.transcription.duration_seconds == original.transcription.duration_seconds
        assert restored.classification.template_name == original.classification.template_name
        assert restored.classification.confidence == original.classification.confidence
        assert restored.notion_page_id == original.notion_page_id
