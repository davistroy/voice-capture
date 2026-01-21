"""Synthesis generator for weekly voice capture summaries.

Generates weekly summaries using Claude API by:
1. Building synthesis prompt from captures
2. Calling Claude API with the prompt
3. Parsing response into structured WeeklySummaryData

Implements TDD section 13.1 and PRD section 8.2 requirements.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from anthropic import Anthropic, APIError, RateLimitError

from src.synthesis.notion_query import VoiceCapture
from src.synthesis.prompt_builder import (
    CaptureStatistics,
    IdeaReference,
    SynthesisPromptBuilder,
    WeeklySummaryData,
)
from src.synthesis.sparse_handler import (
    SparseWeekHandler,
    SparseWeekPromptResult,
)

logger = logging.getLogger(__name__)


class SynthesisGenerationError(Exception):
    """Raised when synthesis generation fails."""
    pass


class SynthesisParseError(SynthesisGenerationError):
    """Raised when parsing synthesis response fails."""
    pass


@dataclass
class SynthesisResult:
    """Result of weekly synthesis generation.

    Attributes:
        summary_data: Structured summary data for template rendering.
        raw_response: Raw JSON response from Claude.
        summary_markdown: Rendered markdown summary.
        start_date: Start of synthesis period.
        end_date: End of synthesis period.
        capture_count: Number of captures included.
        supplemental_input_used: Whether supplemental input was incorporated.
    """
    summary_data: WeeklySummaryData
    raw_response: Dict[str, Any]
    summary_markdown: str
    start_date: datetime
    end_date: datetime
    capture_count: int
    supplemental_input_used: bool = False


class SynthesisGenerator:
    """Generates weekly synthesis summaries using Claude API.

    Coordinates the synthesis generation process:
    1. Detects sparse weeks and handles supplemental input
    2. Builds synthesis prompt from captures
    3. Calls Claude API
    4. Parses response into structured data
    5. Renders final markdown summary

    Args:
        api_key: Anthropic API key.
        model: Claude model to use (default: claude-sonnet-4-20250514).
        max_tokens: Maximum response tokens (default: 4096).
        max_retries: Maximum retry attempts (default: 3).
    """

    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = 3,
    ):
        self._client = Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._prompt_builder = SynthesisPromptBuilder()
        self._sparse_handler = SparseWeekHandler()

    def generate_synthesis(
        self,
        captures: List[VoiceCapture],
        start_date: datetime,
        end_date: datetime,
        supplemental_input: Optional[str] = None,
    ) -> SynthesisResult:
        """Generate weekly synthesis from captures.

        Builds a synthesis prompt from the captures, calls Claude API,
        parses the response, and returns structured summary data.

        Args:
            captures: List of VoiceCapture objects for the period.
            start_date: Start of synthesis period.
            end_date: End of synthesis period.
            supplemental_input: Optional additional context from user.

        Returns:
            SynthesisResult with structured summary data and markdown.

        Raises:
            SynthesisGenerationError: On generation or API failure.
            SynthesisParseError: On response parsing failure.
        """
        logger.info(
            f"Generating synthesis for {len(captures)} captures "
            f"from {start_date.date()} to {end_date.date()}"
        )

        # Build prompt
        prompt = self._prompt_builder.build_synthesis_prompt(
            captures=captures,
            start_date=start_date,
            end_date=end_date,
            supplemental_input=supplemental_input,
        )

        # Call Claude API
        raw_response = self._call_claude_api(prompt)

        # Parse response into structured data
        summary_data = self._parse_response(
            response=raw_response,
            captures=captures,
            start_date=start_date,
            end_date=end_date,
            supplemental_input=supplemental_input,
        )

        # Render markdown
        summary_markdown = self._prompt_builder.render_weekly_summary(summary_data)

        result = SynthesisResult(
            summary_data=summary_data,
            raw_response=raw_response,
            summary_markdown=summary_markdown,
            start_date=start_date,
            end_date=end_date,
            capture_count=len(captures),
            supplemental_input_used=bool(supplemental_input),
        )

        logger.info(f"Successfully generated synthesis with {len(summary_data.accomplishments)} accomplishments")
        return result

    def check_sparse_week(
        self,
        captures: List[VoiceCapture],
    ) -> SparseWeekPromptResult:
        """Check if the week is sparse and get questions if needed.

        Use this method before generate_synthesis() to determine if
        supplemental input should be requested from the user.

        Args:
            captures: List of captures for the week.

        Returns:
            SparseWeekPromptResult with sparse status and questions.
        """
        return self._sparse_handler.create_prompt_result(captures)

    def format_sparse_week_questions(
        self,
        result: SparseWeekPromptResult,
    ) -> str:
        """Format sparse week questions for display to user.

        Args:
            result: SparseWeekPromptResult from check_sparse_week().

        Returns:
            Formatted string with questions for user.
        """
        return self._sparse_handler.format_questions_for_display(result)

    def process_sparse_week_response(
        self,
        result: SparseWeekPromptResult,
        response: str,
    ) -> str:
        """Process user's response to sparse week questions.

        Args:
            result: SparseWeekPromptResult from check_sparse_week().
            response: User's response text.

        Returns:
            Supplemental input text to pass to generate_synthesis().
        """
        updated = self._sparse_handler.process_single_response(result, response)
        return updated.supplemental_text

    def _call_claude_api(self, prompt: str) -> Dict[str, Any]:
        """Call Claude API with synthesis prompt.

        Includes retry logic for transient failures.

        Args:
            prompt: Complete synthesis prompt.

        Returns:
            Parsed JSON response from Claude.

        Raises:
            SynthesisGenerationError: On API failure after retries.
            SynthesisParseError: On invalid JSON response.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries):
            try:
                logger.debug(f"Calling Claude API (attempt {attempt + 1}/{self._max_retries})")

                message = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                )

                # Extract text content
                response_text = ""
                for content_block in message.content:
                    if content_block.type == "text":
                        response_text += content_block.text

                # Parse JSON from response
                return self._extract_json(response_text)

            except RateLimitError as e:
                last_error = e
                logger.warning(f"Rate limited (attempt {attempt + 1}): {e}")
                if attempt < self._max_retries - 1:
                    import time
                    time.sleep(5 * (attempt + 1))  # Simple backoff
                    continue

            except APIError as e:
                last_error = e
                logger.warning(f"API error (attempt {attempt + 1}): {e}")
                if attempt < self._max_retries - 1:
                    import time
                    time.sleep(2 * (attempt + 1))
                    continue

            except SynthesisParseError:
                # Don't retry parse errors
                raise

            except Exception as e:
                last_error = e
                logger.warning(f"Unexpected error (attempt {attempt + 1}): {e}")
                if attempt < self._max_retries - 1:
                    import time
                    time.sleep(2 * (attempt + 1))
                    continue

        raise SynthesisGenerationError(
            f"Failed to generate synthesis after {self._max_retries} attempts: {last_error}"
        )

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract and parse JSON from Claude response.

        Handles responses that may contain markdown code blocks.

        Args:
            text: Raw response text from Claude.

        Returns:
            Parsed JSON dictionary.

        Raises:
            SynthesisParseError: On JSON parsing failure.
        """
        # Try to extract JSON from code block
        json_str = text.strip()

        # Check for markdown code block
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            if end > start:
                json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            if end > start:
                json_str = json_str[start:end].strip()

        # Try to find JSON object directly
        if not json_str.startswith("{"):
            brace_start = json_str.find("{")
            if brace_start >= 0:
                brace_count = 0
                for i, char in enumerate(json_str[brace_start:], brace_start):
                    if char == "{":
                        brace_count += 1
                    elif char == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            json_str = json_str[brace_start:i + 1]
                            break

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {text[:500]}...")
            raise SynthesisParseError(f"Invalid JSON in response: {e}") from e

    def _parse_response(
        self,
        response: Dict[str, Any],
        captures: List[VoiceCapture],
        start_date: datetime,
        end_date: datetime,
        supplemental_input: Optional[str] = None,
    ) -> WeeklySummaryData:
        """Parse Claude response into WeeklySummaryData.

        Validates response structure and extracts all fields.

        Args:
            response: Parsed JSON response.
            captures: Original captures for statistics.
            start_date: Start of synthesis period.
            end_date: End of synthesis period.
            supplemental_input: Supplemental input if provided.

        Returns:
            WeeklySummaryData with all summary fields.

        Raises:
            SynthesisParseError: On validation failure.
        """
        try:
            # Extract and validate required fields
            overview = response.get("overview", "")
            accomplishments = response.get("accomplishments", [])
            key_activities = response.get("key_activities", "")
            challenges = response.get("challenges", [])
            insights = response.get("insights", "")
            upcoming = response.get("upcoming", [])

            # Parse ideas with links
            ideas = []
            for idea_data in response.get("ideas", []):
                if isinstance(idea_data, dict):
                    ideas.append(IdeaReference(
                        title=idea_data.get("title", "Untitled"),
                        url=idea_data.get("url", ""),
                        summary=idea_data.get("summary", ""),
                    ))

            # Build statistics
            stats = self._build_statistics(
                captures=captures,
                supplemental_input_used=bool(supplemental_input),
            )

            return WeeklySummaryData(
                start_date=start_date.strftime("%B %d, %Y"),
                end_date=end_date.strftime("%B %d, %Y"),
                overview=overview,
                accomplishments=accomplishments if isinstance(accomplishments, list) else [],
                key_activities=key_activities,
                challenges=challenges if isinstance(challenges, list) else [],
                ideas=ideas,
                insights=insights,
                upcoming=upcoming if isinstance(upcoming, list) else [],
                stats=stats,
            )

        except Exception as e:
            logger.error(f"Failed to parse synthesis response: {e}")
            raise SynthesisParseError(f"Failed to parse response structure: {e}") from e

    def _build_statistics(
        self,
        captures: List[VoiceCapture],
        supplemental_input_used: bool = False,
    ) -> CaptureStatistics:
        """Build capture statistics from captures list.

        Args:
            captures: List of captures.
            supplemental_input_used: Whether supplemental input was used.

        Returns:
            CaptureStatistics with computed values.
        """
        # Count by type
        by_type: Dict[str, int] = {}
        total_duration = 0.0

        for capture in captures:
            template_type = capture.template_type or "General"
            by_type[template_type] = by_type.get(template_type, 0) + 1

            # Extract duration if available
            duration_prop = capture.properties.get("Duration", {})
            if duration_prop.get("type") == "number":
                duration_val = duration_prop.get("number")
                if duration_val is not None:
                    total_duration += float(duration_val)

        return CaptureStatistics(
            total_captures=len(captures),
            by_type=by_type,
            total_duration_seconds=total_duration,
            supplemental_input_used=supplemental_input_used,
        )


def generate_synthesis(
    api_key: str,
    captures: List[VoiceCapture],
    start_date: datetime,
    end_date: datetime,
    supplemental_input: Optional[str] = None,
    model: str = SynthesisGenerator.DEFAULT_MODEL,
) -> SynthesisResult:
    """Convenience function to generate synthesis without instantiating generator.

    Args:
        api_key: Anthropic API key.
        captures: List of VoiceCapture objects for the period.
        start_date: Start of synthesis period.
        end_date: End of synthesis period.
        supplemental_input: Optional additional context from user.
        model: Claude model to use.

    Returns:
        SynthesisResult with structured summary data and markdown.

    Raises:
        SynthesisGenerationError: On generation failure.
    """
    generator = SynthesisGenerator(api_key=api_key, model=model)
    return generator.generate_synthesis(
        captures=captures,
        start_date=start_date,
        end_date=end_date,
        supplemental_input=supplemental_input,
    )
