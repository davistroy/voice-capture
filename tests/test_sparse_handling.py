"""Tests for sparse week handling module.

Tests cover:
- Sparse week detection (< 3 captures threshold)
- Question generation per PRD section 8.3
- Response processing (individual and combined)
- Supplemental input formatting
- Context string generation for synthesis
"""

from datetime import datetime
from typing import List

import pytest

from src.synthesis.notion_query import VoiceCapture
from src.synthesis.sparse_handler import (
    SPARSE_WEEK_THRESHOLD,
    SparseWeekHandler,
    SparseWeekPromptResult,
    SparseWeekQuestion,
    build_sparse_week_context,
    detect_sparse_week,
    format_supplemental_input,
    get_sparse_week_questions,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_capture() -> VoiceCapture:
    """Create a single sample capture."""
    return VoiceCapture(
        id="capture-1",
        url="https://notion.so/capture-1",
        title="Sample capture",
        captured_at=datetime(2026, 1, 20, 14, 30),
        template_type="Task",
        device="Watch",
        tags=["work"],
        content="Sample content",
    )


@pytest.fixture
def sparse_captures(sample_capture: VoiceCapture) -> List[VoiceCapture]:
    """Create a sparse week (< 3 captures)."""
    return [
        sample_capture,
        VoiceCapture(
            id="capture-2",
            url="https://notion.so/capture-2",
            title="Second capture",
            captured_at=datetime(2026, 1, 21, 9, 0),
            template_type="Journal",
            device="Phone",
            tags=[],
            content="Second capture content",
        ),
    ]


@pytest.fixture
def normal_captures(sample_capture: VoiceCapture) -> List[VoiceCapture]:
    """Create a normal week (>= 3 captures)."""
    return [
        sample_capture,
        VoiceCapture(
            id="capture-2",
            url="https://notion.so/capture-2",
            title="Second capture",
            captured_at=datetime(2026, 1, 21, 9, 0),
            template_type="Journal",
            device="Phone",
            tags=[],
            content="Second capture content",
        ),
        VoiceCapture(
            id="capture-3",
            url="https://notion.so/capture-3",
            title="Third capture",
            captured_at=datetime(2026, 1, 22, 10, 0),
            template_type="Idea",
            device="Watch",
            tags=["brainstorm"],
            content="Third capture content",
        ),
    ]


@pytest.fixture
def many_captures(sample_capture: VoiceCapture) -> List[VoiceCapture]:
    """Create a week with many captures."""
    captures = []
    for i in range(10):
        captures.append(
            VoiceCapture(
                id=f"capture-{i}",
                url=f"https://notion.so/capture-{i}",
                title=f"Capture {i}",
                captured_at=datetime(2026, 1, 20 + (i % 7), 9, 0),
                template_type="Task" if i % 2 == 0 else "Journal",
                device="Watch",
                tags=[],
                content=f"Content {i}",
            )
        )
    return captures


@pytest.fixture
def handler() -> SparseWeekHandler:
    """Create a SparseWeekHandler with default settings."""
    return SparseWeekHandler()


# ============================================================================
# SparseWeekQuestion Tests
# ============================================================================


class TestSparseWeekQuestion:
    """Tests for SparseWeekQuestion enum."""

    def test_question_values(self):
        """Test that question enum has correct values per PRD 8.3."""
        assert SparseWeekQuestion.WORK_FOCUS.value == "What were your main work focuses this week?"
        assert SparseWeekQuestion.MEETINGS.value == "Any significant meetings or conversations?"
        assert SparseWeekQuestion.CARRYOVER.value == "What's carrying over to next week?"

    def test_all_questions_are_strings(self):
        """Test all question values are non-empty strings."""
        for question in SparseWeekQuestion:
            assert isinstance(question.value, str)
            assert len(question.value) > 0

    def test_question_count(self):
        """Test we have exactly 3 questions per PRD 8.3."""
        assert len(SparseWeekQuestion) == 3


# ============================================================================
# SparseWeekPromptResult Tests
# ============================================================================


class TestSparseWeekPromptResult:
    """Tests for SparseWeekPromptResult dataclass."""

    def test_default_values(self):
        """Test default values for SparseWeekPromptResult."""
        result = SparseWeekPromptResult(
            is_sparse=True,
            capture_count=2,
        )
        assert result.is_sparse is True
        assert result.capture_count == 2
        assert result.questions == []
        assert result.questions_asked is False
        assert result.responses == []
        assert result.supplemental_text == ""

    def test_has_supplemental_input_false(self):
        """Test has_supplemental_input returns False when empty."""
        result = SparseWeekPromptResult(
            is_sparse=True,
            capture_count=2,
            supplemental_text="",
        )
        assert result.has_supplemental_input() is False

    def test_has_supplemental_input_whitespace(self):
        """Test has_supplemental_input returns False for whitespace only."""
        result = SparseWeekPromptResult(
            is_sparse=True,
            capture_count=2,
            supplemental_text="   \n\t  ",
        )
        assert result.has_supplemental_input() is False

    def test_has_supplemental_input_true(self):
        """Test has_supplemental_input returns True when text present."""
        result = SparseWeekPromptResult(
            is_sparse=True,
            capture_count=2,
            supplemental_text="User provided context here.",
        )
        assert result.has_supplemental_input() is True


# ============================================================================
# SparseWeekHandler Tests
# ============================================================================


class TestSparseWeekHandler:
    """Tests for SparseWeekHandler class."""

    def test_default_threshold(self, handler: SparseWeekHandler):
        """Test default threshold is 3."""
        assert handler.threshold == SPARSE_WEEK_THRESHOLD
        assert handler.threshold == 3

    def test_custom_threshold(self):
        """Test custom threshold setting."""
        handler = SparseWeekHandler(threshold=5)
        assert handler.threshold == 5

    def test_default_questions(self, handler: SparseWeekHandler):
        """Test default questions are loaded."""
        questions = handler.get_questions()
        assert len(questions) == 3
        assert "What were your main work focuses this week?" in questions
        assert "Any significant meetings or conversations?" in questions
        assert "What's carrying over to next week?" in questions

    def test_custom_questions(self):
        """Test custom questions override defaults."""
        custom = ["Question 1?", "Question 2?"]
        handler = SparseWeekHandler(custom_questions=custom)
        questions = handler.get_questions()
        assert questions == custom

    def test_is_sparse_week_true_zero(self, handler: SparseWeekHandler):
        """Test sparse detection with zero captures."""
        assert handler.is_sparse_week([]) is True

    def test_is_sparse_week_true_one(
        self, handler: SparseWeekHandler, sample_capture: VoiceCapture
    ):
        """Test sparse detection with one capture."""
        assert handler.is_sparse_week([sample_capture]) is True

    def test_is_sparse_week_true_two(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test sparse detection with two captures (below threshold)."""
        assert handler.is_sparse_week(sparse_captures) is True

    def test_is_sparse_week_false_three(
        self, handler: SparseWeekHandler, normal_captures: List[VoiceCapture]
    ):
        """Test non-sparse detection with exactly 3 captures (at threshold)."""
        assert handler.is_sparse_week(normal_captures) is False

    def test_is_sparse_week_false_many(
        self, handler: SparseWeekHandler, many_captures: List[VoiceCapture]
    ):
        """Test non-sparse detection with many captures."""
        assert handler.is_sparse_week(many_captures) is False

    def test_is_sparse_week_custom_threshold(
        self, normal_captures: List[VoiceCapture]
    ):
        """Test sparse detection with custom threshold."""
        handler = SparseWeekHandler(threshold=5)
        # 3 captures is sparse when threshold is 5
        assert handler.is_sparse_week(normal_captures) is True


class TestSparseWeekHandlerPromptResult:
    """Tests for SparseWeekHandler.create_prompt_result method."""

    def test_create_prompt_result_sparse(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test prompt result for sparse week."""
        result = handler.create_prompt_result(sparse_captures)

        assert result.is_sparse is True
        assert result.capture_count == 2
        assert len(result.questions) == 3
        assert result.questions_asked is False
        assert result.responses == []
        assert result.supplemental_text == ""

    def test_create_prompt_result_normal(
        self, handler: SparseWeekHandler, normal_captures: List[VoiceCapture]
    ):
        """Test prompt result for normal week."""
        result = handler.create_prompt_result(normal_captures)

        assert result.is_sparse is False
        assert result.capture_count == 3
        assert result.questions == []  # No questions for normal weeks
        assert result.questions_asked is False

    def test_create_prompt_result_empty(self, handler: SparseWeekHandler):
        """Test prompt result for zero captures."""
        result = handler.create_prompt_result([])

        assert result.is_sparse is True
        assert result.capture_count == 0
        assert len(result.questions) == 3


class TestSparseWeekHandlerFormatQuestions:
    """Tests for SparseWeekHandler.format_questions_for_display method."""

    def test_format_questions_sparse(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test formatting questions for sparse week."""
        result = handler.create_prompt_result(sparse_captures)
        formatted = handler.format_questions_for_display(result)

        assert "I found only 2 capture(s) this week" in formatted
        assert "1. What were your main work focuses this week?" in formatted
        assert "2. Any significant meetings or conversations?" in formatted
        assert "3. What's carrying over to next week?" in formatted

    def test_format_questions_without_context(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test formatting questions without introductory context."""
        result = handler.create_prompt_result(sparse_captures)
        formatted = handler.format_questions_for_display(result, include_context=False)

        assert "I found only" not in formatted
        assert "1. What were your main work focuses this week?" in formatted

    def test_format_questions_normal_week(
        self, handler: SparseWeekHandler, normal_captures: List[VoiceCapture]
    ):
        """Test formatting returns empty for normal week."""
        result = handler.create_prompt_result(normal_captures)
        formatted = handler.format_questions_for_display(result)

        assert formatted == ""


class TestSparseWeekHandlerProcessResponses:
    """Tests for SparseWeekHandler.process_responses method."""

    def test_process_responses_full(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test processing all three responses."""
        result = handler.create_prompt_result(sparse_captures)

        responses = [
            "Focused on the Q4 report and dashboard project.",
            "Had a planning meeting with the team on Wednesday.",
            "Need to finish the dashboard and prepare for demo.",
        ]

        updated = handler.process_responses(result, responses)

        assert updated.questions_asked is True
        assert updated.responses == responses
        assert updated.has_supplemental_input() is True

        # Check supplemental text contains all responses
        text = updated.supplemental_text
        assert "What were your main work focuses this week?" in text
        assert "Q4 report and dashboard project" in text
        assert "Any significant meetings or conversations?" in text
        assert "planning meeting with the team" in text
        assert "What's carrying over to next week?" in text
        assert "finish the dashboard" in text

    def test_process_responses_partial(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test processing partial responses (some empty)."""
        result = handler.create_prompt_result(sparse_captures)

        responses = [
            "Worked on the quarterly report.",
            "",  # Empty response
            "Dashboard work continues.",
        ]

        updated = handler.process_responses(result, responses)

        assert updated.questions_asked is True
        text = updated.supplemental_text

        # Should include non-empty responses only
        assert "quarterly report" in text
        assert "Dashboard work continues" in text

    def test_process_responses_empty(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test processing all empty responses."""
        result = handler.create_prompt_result(sparse_captures)

        responses = ["", "", ""]

        updated = handler.process_responses(result, responses)

        assert updated.questions_asked is True
        assert updated.supplemental_text == ""
        assert updated.has_supplemental_input() is False

    def test_process_responses_extra(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test processing more responses than questions."""
        result = handler.create_prompt_result(sparse_captures)

        responses = [
            "Work focus answer.",
            "Meetings answer.",
            "Carryover answer.",
            "Additional context provided by user.",
        ]

        updated = handler.process_responses(result, responses)

        text = updated.supplemental_text
        assert "Additional context" in text
        assert "Additional context provided by user" in text


class TestSparseWeekHandlerProcessSingleResponse:
    """Tests for SparseWeekHandler.process_single_response method."""

    def test_process_single_response(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test processing a single combined response."""
        result = handler.create_prompt_result(sparse_captures)

        response = (
            "This week I mainly focused on the quarterly report. "
            "Had a great planning session with the team. "
            "Need to wrap up the dashboard next week."
        )

        updated = handler.process_single_response(result, response)

        assert updated.questions_asked is True
        assert updated.responses == [response]
        assert updated.has_supplemental_input() is True
        assert "additional context about their week" in updated.supplemental_text
        assert "quarterly report" in updated.supplemental_text

    def test_process_single_response_empty(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test processing empty single response."""
        result = handler.create_prompt_result(sparse_captures)

        updated = handler.process_single_response(result, "   ")

        assert updated.questions_asked is True
        # Even empty, the context text is included
        assert "additional context about their week" in updated.supplemental_text


# ============================================================================
# Convenience Function Tests
# ============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_detect_sparse_week_true(self, sparse_captures: List[VoiceCapture]):
        """Test detect_sparse_week returns True for sparse."""
        assert detect_sparse_week(sparse_captures) is True

    def test_detect_sparse_week_false(self, normal_captures: List[VoiceCapture]):
        """Test detect_sparse_week returns False for normal."""
        assert detect_sparse_week(normal_captures) is False

    def test_detect_sparse_week_custom_threshold(
        self, normal_captures: List[VoiceCapture]
    ):
        """Test detect_sparse_week with custom threshold."""
        assert detect_sparse_week(normal_captures, threshold=5) is True
        assert detect_sparse_week(normal_captures, threshold=3) is False

    def test_get_sparse_week_questions(self):
        """Test get_sparse_week_questions returns correct questions."""
        questions = get_sparse_week_questions()

        assert len(questions) == 3
        assert "What were your main work focuses this week?" in questions
        assert "Any significant meetings or conversations?" in questions
        assert "What's carrying over to next week?" in questions

    def test_format_supplemental_input(self):
        """Test format_supplemental_input formatting."""
        questions = [
            "Question 1?",
            "Question 2?",
        ]
        responses = [
            "Answer 1.",
            "Answer 2.",
        ]

        text = format_supplemental_input(questions, responses)

        assert "**Question 1?**" in text
        assert "Answer 1." in text
        assert "**Question 2?**" in text
        assert "Answer 2." in text

    def test_format_supplemental_input_empty(self):
        """Test format_supplemental_input with empty responses."""
        questions = ["Question 1?"]
        responses = []

        text = format_supplemental_input(questions, responses)
        assert text == ""

    def test_format_supplemental_input_partial(self):
        """Test format_supplemental_input with partial responses."""
        questions = ["Question 1?", "Question 2?"]
        responses = ["Answer 1.", ""]

        text = format_supplemental_input(questions, responses)

        assert "**Question 1?**" in text
        assert "Answer 1." in text
        # Empty response should not be included
        assert "Question 2?" not in text

    def test_build_sparse_week_context(self):
        """Test build_sparse_week_context string generation."""
        context = build_sparse_week_context(
            capture_count=2,
            supplemental_text="User provided context.",
        )

        assert "sparse week with only 2 capture(s)" in context
        assert "supplemental input provided by the user" in context

    def test_build_sparse_week_context_empty(self):
        """Test build_sparse_week_context with no supplemental text."""
        context = build_sparse_week_context(
            capture_count=2,
            supplemental_text="",
        )

        assert context == ""


# ============================================================================
# Integration Tests
# ============================================================================


class TestSparseHandlerIntegration:
    """Integration tests for sparse week handling workflow."""

    def test_full_sparse_week_workflow(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test complete workflow for sparse week handling."""
        # 1. Detect sparse week and create prompt result
        result = handler.create_prompt_result(sparse_captures)
        assert result.is_sparse is True

        # 2. Format questions for display
        formatted = handler.format_questions_for_display(result)
        assert "What were your main work focuses" in formatted

        # 3. Process user responses
        responses = [
            "Focused on client deliverables.",
            "Key meeting with stakeholders.",
            "Follow-up tasks from the meeting.",
        ]
        result = handler.process_responses(result, responses)

        # 4. Verify supplemental input is ready for synthesis
        assert result.has_supplemental_input() is True
        assert "client deliverables" in result.supplemental_text
        assert "stakeholders" in result.supplemental_text

        # 5. Build context string for synthesis
        context = build_sparse_week_context(
            capture_count=result.capture_count,
            supplemental_text=result.supplemental_text,
        )
        assert "sparse week" in context

    def test_normal_week_workflow(
        self, handler: SparseWeekHandler, normal_captures: List[VoiceCapture]
    ):
        """Test workflow skips prompting for normal week."""
        result = handler.create_prompt_result(normal_captures)

        assert result.is_sparse is False
        assert result.questions == []

        # Formatting should return empty
        formatted = handler.format_questions_for_display(result)
        assert formatted == ""

        # Context should be empty
        context = build_sparse_week_context(
            capture_count=result.capture_count,
            supplemental_text="",
        )
        assert context == ""

    def test_single_response_workflow(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test workflow with single combined response (e.g., verbal input)."""
        result = handler.create_prompt_result(sparse_captures)

        # User provides all info in one response
        combined_response = (
            "This week was mostly about the quarterly review. "
            "Met with finance team on Thursday. "
            "Still need to finalize the budget projections."
        )

        result = handler.process_single_response(result, combined_response)

        assert result.has_supplemental_input() is True
        assert "quarterly review" in result.supplemental_text
        assert "finance team" in result.supplemental_text
        assert "budget projections" in result.supplemental_text


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_threshold_of_one(self, sample_capture: VoiceCapture):
        """Test with threshold of 1 capture."""
        handler = SparseWeekHandler(threshold=1)

        # Zero captures is still sparse
        assert handler.is_sparse_week([]) is True

        # One capture meets threshold
        assert handler.is_sparse_week([sample_capture]) is False

    def test_very_high_threshold(self, many_captures: List[VoiceCapture]):
        """Test with very high threshold."""
        handler = SparseWeekHandler(threshold=100)

        # Even 10 captures is sparse with threshold 100
        assert handler.is_sparse_week(many_captures) is True

    def test_response_with_special_characters(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test processing responses with special characters."""
        result = handler.create_prompt_result(sparse_captures)

        responses = [
            "Worked on the Q4 report & dashboard <project>.",
            "Meeting with \"John\" about the 'strategy'.",
            "Tasks: 1) Finish docs, 2) Review PR.",
        ]

        updated = handler.process_responses(result, responses)

        # All special characters should be preserved
        assert "Q4 report & dashboard <project>" in updated.supplemental_text
        assert '"John"' in updated.supplemental_text
        assert "Tasks: 1) Finish docs" in updated.supplemental_text

    def test_multiline_response(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test processing multiline responses."""
        result = handler.create_prompt_result(sparse_captures)

        responses = [
            "First line of answer.\nSecond line.\nThird line.",
            "Single line answer.",
            "Multi\nLine\nAnswer.",
        ]

        updated = handler.process_responses(result, responses)

        assert "First line of answer." in updated.supplemental_text
        assert "Second line." in updated.supplemental_text

    def test_empty_custom_questions(
        self, sparse_captures: List[VoiceCapture]
    ):
        """Test handler with empty custom questions list."""
        handler = SparseWeekHandler(custom_questions=[])

        result = handler.create_prompt_result(sparse_captures)

        # Still sparse, but no questions
        assert result.is_sparse is True
        assert result.questions == []

    def test_whitespace_only_responses(
        self, handler: SparseWeekHandler, sparse_captures: List[VoiceCapture]
    ):
        """Test processing whitespace-only responses."""
        result = handler.create_prompt_result(sparse_captures)

        responses = [
            "   ",
            "\t\n",
            "  \n  \t  ",
        ]

        updated = handler.process_responses(result, responses)

        # Whitespace should be stripped, resulting in empty
        assert updated.questions_asked is True
        assert updated.supplemental_text == ""
