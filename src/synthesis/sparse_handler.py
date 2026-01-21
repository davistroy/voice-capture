"""Sparse week handling for weekly synthesis.

Handles weeks with few captures (< 3) by prompting for supplemental input
to ensure meaningful weekly summaries can still be generated.

Per PRD section 8.3:
- Detect sparse weeks (< 3 captures)
- Generate targeted questions to gather additional context
- Accept verbal/text responses
- Incorporate supplemental input into synthesis
- Note in summary that supplemental input was included
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

from src.synthesis.notion_query import VoiceCapture

logger = logging.getLogger(__name__)


# Default threshold for sparse week detection
SPARSE_WEEK_THRESHOLD = 3


class SparseWeekQuestion(Enum):
    """Predefined questions for sparse week prompting per PRD section 8.3."""

    WORK_FOCUS = "What were your main work focuses this week?"
    MEETINGS = "Any significant meetings or conversations?"
    CARRYOVER = "What's carrying over to next week?"


@dataclass
class SparseWeekPromptResult:
    """Result of sparse week detection and prompting.

    Attributes:
        is_sparse: Whether the week is considered sparse.
        capture_count: Number of captures in the week.
        questions: List of questions to ask the user.
        questions_asked: Whether questions have been presented to user.
        responses: User responses to the questions.
        supplemental_text: Combined supplemental input text.
    """

    is_sparse: bool
    capture_count: int
    questions: List[str] = field(default_factory=list)
    questions_asked: bool = False
    responses: List[str] = field(default_factory=list)
    supplemental_text: str = ""

    def has_supplemental_input(self) -> bool:
        """Check if supplemental input was provided."""
        return bool(self.supplemental_text.strip())


@dataclass
class SparseWeekHandler:
    """Handler for sparse week detection and supplemental input gathering.

    Detects weeks with fewer than the threshold captures and generates
    targeted questions to gather additional context for synthesis.

    Args:
        threshold: Minimum captures for a non-sparse week (default 3).
        custom_questions: Optional custom questions to use instead of defaults.
    """

    threshold: int = SPARSE_WEEK_THRESHOLD
    custom_questions: Optional[List[str]] = None

    def __post_init__(self):
        """Initialize default questions if none provided."""
        if self.custom_questions is None:
            self.custom_questions = [q.value for q in SparseWeekQuestion]

    def is_sparse_week(self, captures: List[VoiceCapture]) -> bool:
        """Check if the week is sparse (below threshold).

        Args:
            captures: List of captures for the week.

        Returns:
            True if capture count is below threshold.
        """
        is_sparse = len(captures) < self.threshold
        if is_sparse:
            logger.info(
                f"Sparse week detected: {len(captures)} captures "
                f"(threshold: {self.threshold})"
            )
        return is_sparse

    def get_questions(self) -> List[str]:
        """Get the list of questions to ask for sparse weeks.

        Returns:
            List of question strings.
        """
        return list(self.custom_questions or [])

    def create_prompt_result(
        self,
        captures: List[VoiceCapture],
    ) -> SparseWeekPromptResult:
        """Create a prompt result based on capture analysis.

        Args:
            captures: List of captures for the week.

        Returns:
            SparseWeekPromptResult with sparse status and questions.
        """
        is_sparse = self.is_sparse_week(captures)
        questions = self.get_questions() if is_sparse else []

        return SparseWeekPromptResult(
            is_sparse=is_sparse,
            capture_count=len(captures),
            questions=questions,
            questions_asked=False,
            responses=[],
            supplemental_text="",
        )

    def format_questions_for_display(
        self,
        result: SparseWeekPromptResult,
        include_context: bool = True,
    ) -> str:
        """Format questions for display to user.

        Args:
            result: SparseWeekPromptResult with questions.
            include_context: Whether to include introductory context.

        Returns:
            Formatted string for display.
        """
        if not result.is_sparse:
            return ""

        lines = []

        if include_context:
            lines.append(
                f"I found only {result.capture_count} capture(s) this week. "
                "To create a more useful summary, please answer the following questions:"
            )
            lines.append("")

        for i, question in enumerate(result.questions, 1):
            lines.append(f"{i}. {question}")

        return "\n".join(lines)

    def process_responses(
        self,
        result: SparseWeekPromptResult,
        responses: List[str],
    ) -> SparseWeekPromptResult:
        """Process user responses and generate supplemental text.

        Combines question-response pairs into formatted supplemental text
        that can be incorporated into the synthesis prompt.

        Args:
            result: Original SparseWeekPromptResult.
            responses: User responses (one per question).

        Returns:
            Updated SparseWeekPromptResult with supplemental text.
        """
        # Update result with responses
        result.questions_asked = True
        result.responses = responses

        # Build supplemental text from question-response pairs
        text_parts = []
        questions = result.questions

        for i, (question, response) in enumerate(zip(questions, responses)):
            response_text = response.strip()
            if response_text:
                text_parts.append(f"**{question}**")
                text_parts.append(response_text)
                text_parts.append("")

        # Handle any extra responses beyond the questions
        if len(responses) > len(questions):
            extra_responses = responses[len(questions) :]
            for response in extra_responses:
                response_text = response.strip()
                if response_text:
                    text_parts.append("**Additional context:**")
                    text_parts.append(response_text)
                    text_parts.append("")

        result.supplemental_text = "\n".join(text_parts).strip()

        logger.info(
            f"Processed {len(responses)} response(s) for sparse week, "
            f"generated {len(result.supplemental_text)} chars of supplemental text"
        )

        return result

    def process_single_response(
        self,
        result: SparseWeekPromptResult,
        response: str,
    ) -> SparseWeekPromptResult:
        """Process a single combined response (text or verbal).

        Used when the user provides all answers in one response rather
        than answering each question individually.

        Args:
            result: Original SparseWeekPromptResult.
            response: Single combined response text.

        Returns:
            Updated SparseWeekPromptResult with supplemental text.
        """
        result.questions_asked = True
        result.responses = [response]

        # Format as supplemental input
        text_parts = [
            "The user provided the following additional context about their week:",
            "",
            response.strip(),
        ]

        result.supplemental_text = "\n".join(text_parts)

        logger.info(
            f"Processed single response for sparse week, "
            f"generated {len(result.supplemental_text)} chars of supplemental text"
        )

        return result


def detect_sparse_week(
    captures: List[VoiceCapture],
    threshold: int = SPARSE_WEEK_THRESHOLD,
) -> bool:
    """Convenience function to detect sparse week.

    Args:
        captures: List of captures for the week.
        threshold: Minimum captures for non-sparse week.

    Returns:
        True if capture count is below threshold.
    """
    return len(captures) < threshold


def get_sparse_week_questions() -> List[str]:
    """Get the default sparse week questions.

    Returns:
        List of question strings per PRD section 8.3.
    """
    return [q.value for q in SparseWeekQuestion]


def format_supplemental_input(
    questions: List[str],
    responses: List[str],
) -> str:
    """Format questions and responses into supplemental input text.

    Args:
        questions: List of questions asked.
        responses: List of user responses.

    Returns:
        Formatted supplemental text for synthesis prompt.
    """
    if not responses:
        return ""

    text_parts = []

    for question, response in zip(questions, responses):
        response_text = response.strip()
        if response_text:
            text_parts.append(f"**{question}**")
            text_parts.append(response_text)
            text_parts.append("")

    return "\n".join(text_parts).strip()


def build_sparse_week_context(
    capture_count: int,
    supplemental_text: str,
) -> str:
    """Build context string noting sparse week and supplemental input.

    This string can be included in the synthesis to indicate that
    supplemental input was used due to a sparse week.

    Args:
        capture_count: Number of captures in the week.
        supplemental_text: The supplemental input text.

    Returns:
        Context string for synthesis.
    """
    if not supplemental_text:
        return ""

    return (
        f"Note: This was a sparse week with only {capture_count} capture(s). "
        "The summary incorporates supplemental input provided by the user "
        "to fill in context about the week."
    )
