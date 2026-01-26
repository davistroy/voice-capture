"""
Classification response parser.

Parses and validates LLM JSON responses, applying defaults
and handling validation errors per TDD Section 4.3.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.classification.template_loader import TemplateLoader
from src.classification.template_config import TemplateConfig
from src.models.classification import ClassificationResult


logger = logging.getLogger(__name__)


class ParseError(Exception):
    """Raised when JSON parsing fails."""

    def __init__(self, message: str, raw_response: str):
        self.message = message
        self.raw_response = raw_response
        super().__init__(message)


class ValidationError(Exception):
    """Raised when response validation fails."""

    def __init__(self, message: str, field: str):
        self.message = message
        self.field = field
        super().__init__(f"{field}: {message}")


@dataclass
class ParsedResponse:
    """
    Intermediate representation of a parsed LLM response.

    Contains raw parsed values before validation and normalization.
    """
    template: str
    confidence: float
    reasoning: Optional[str]
    title: str
    tags: List[str]
    fields: Dict[str, Any]


class ResponseParser:
    """
    Parses and validates classification responses from Claude.

    Handles:
    - JSON extraction from response text
    - Schema validation
    - Template existence verification
    - Confidence range validation
    - Required field validation
    - Default value application
    """

    def __init__(
        self,
        template_loader: TemplateLoader,
        confidence_threshold: float = 0.7,
        fallback_template: str = "general",
    ):
        """
        Initialize the response parser.

        Args:
            template_loader: Loaded template configurations.
            confidence_threshold: Threshold for fallback to general.
            fallback_template: Template to use when confidence is low.
        """
        self.template_loader = template_loader
        self.confidence_threshold = confidence_threshold
        self.fallback_template = fallback_template

    def parse(self, response_text: str) -> ClassificationResult:
        """
        Parse and validate an LLM response into a ClassificationResult.

        Args:
            response_text: Raw response text from Claude API.

        Returns:
            Validated ClassificationResult.

        Raises:
            ParseError: If JSON cannot be extracted or parsed.
            ValidationError: If required fields are missing or invalid.
        """
        # Extract and parse JSON
        json_data = self._extract_json(response_text)
        parsed = self._parse_json(json_data)

        # Validate and normalize
        validated = self._validate_response(parsed)

        # Apply confidence threshold logic
        result = self._apply_threshold_logic(validated)

        return result

    def _extract_json(self, response_text: str) -> str:
        """
        Extract JSON from response text.

        Handles cases where the response includes markdown code blocks
        or other surrounding text.

        Args:
            response_text: Raw response text.

        Returns:
            Extracted JSON string.

        Raises:
            ParseError: If no JSON found in response.
        """
        text = response_text.strip()

        # Try to find JSON in code blocks first
        code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        code_matches = re.findall(code_block_pattern, text)
        if code_matches:
            for match in code_matches:
                if self._looks_like_json(match):
                    return match.strip()

        # Try to find raw JSON object
        # Look for content between first { and last }
        first_brace = text.find('{')
        last_brace = text.rfind('}')

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            potential_json = text[first_brace:last_brace + 1]
            if self._looks_like_json(potential_json):
                return potential_json

        # If the whole text looks like JSON, return it
        if self._looks_like_json(text):
            return text

        raise ParseError(
            "Could not extract JSON from response",
            response_text
        )

    def _looks_like_json(self, text: str) -> bool:
        """Check if text looks like it could be JSON."""
        text = text.strip()
        return (
            text.startswith('{') and
            text.endswith('}') and
            '"template"' in text
        )

    def _parse_json(self, json_str: str) -> ParsedResponse:
        """
        Parse JSON string into ParsedResponse.

        Args:
            json_str: JSON string to parse.

        Returns:
            ParsedResponse with extracted values.

        Raises:
            ParseError: If JSON is invalid.
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ParseError(f"Invalid JSON: {e}", json_str)

        if not isinstance(data, dict):
            raise ParseError("Response must be a JSON object", json_str)

        # Extract required fields with type checking
        template = self._get_string(data, "template", json_str)
        confidence = self._get_number(data, "confidence", json_str)
        title = self._get_string(data, "title", json_str)

        # Extract optional fields with defaults
        reasoning = data.get("reasoning")
        if reasoning is not None and not isinstance(reasoning, str):
            reasoning = str(reasoning)

        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t) for t in tags if t is not None]

        fields = data.get("fields", {})
        if not isinstance(fields, dict):
            fields = {}

        return ParsedResponse(
            template=template,
            confidence=confidence,
            reasoning=reasoning,
            title=title,
            tags=tags,
            fields=fields,
        )

    def _get_string(
        self,
        data: Dict[str, Any],
        key: str,
        raw: str
    ) -> str:
        """Extract a required string field."""
        value = data.get(key)
        if value is None:
            raise ParseError(f"Missing required field: {key}", raw)
        return str(value)

    def _get_number(
        self,
        data: Dict[str, Any],
        key: str,
        raw: str
    ) -> float:
        """Extract a required number field."""
        value = data.get(key)
        if value is None:
            raise ParseError(f"Missing required field: {key}", raw)
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ParseError(f"Field '{key}' must be a number", raw)

    def _validate_response(self, parsed: ParsedResponse) -> ParsedResponse:
        """
        Validate parsed response against schema and template definitions.

        Args:
            parsed: Parsed response to validate.

        Returns:
            Validated response (may be modified).

        Raises:
            ValidationError: If validation fails.
        """
        # Validate confidence range
        if not 0.0 <= parsed.confidence <= 1.0:
            raise ValidationError(
                f"Confidence must be between 0.0 and 1.0, got {parsed.confidence}",
                "confidence"
            )

        # Validate template exists or use fallback
        template_name = parsed.template.lower()
        if not self.template_loader.has_template(template_name):
            logger.warning(
                f"Unknown template '{parsed.template}', using fallback"
            )
            parsed.template = self.fallback_template
            template_name = self.fallback_template

        # Validate title is not empty
        if not parsed.title.strip():
            raise ValidationError("Title cannot be empty", "title")

        # Validate and apply defaults for fields
        template = self.template_loader.get_template(template_name)
        if template:
            parsed.fields = self._validate_fields(parsed.fields, template)

        # Normalize tags
        parsed.tags = self._normalize_tags(parsed.tags)

        return parsed

    def _validate_fields(
        self,
        fields: Dict[str, Any],
        template: TemplateConfig,
    ) -> Dict[str, Any]:
        """
        Validate extracted fields against template definition.

        Args:
            fields: Extracted field values.
            template: Template configuration.

        Returns:
            Validated fields with defaults applied.
        """
        validated = {}

        for field_config in template.fields:
            field_name = field_config.name
            value = fields.get(field_name)

            if value is not None:
                # Field was extracted - use it
                validated[field_name] = value
            elif field_config.required:
                # Required field missing - this is a problem but we'll
                # handle it gracefully by using empty string
                logger.warning(
                    f"Missing required field '{field_name}' for template "
                    f"'{template.name}', using empty value"
                )
                validated[field_name] = ""
            elif field_config.default is not None:
                # Optional field with default
                validated[field_name] = field_config.default
            # else: Optional field with no default - leave out

        return validated

    def _normalize_tags(self, tags: List[str]) -> List[str]:
        """
        Normalize tag list.

        - Lowercase all tags
        - Remove duplicates
        - Remove empty strings
        - Limit to reasonable count

        Args:
            tags: Raw tag list.

        Returns:
            Normalized tag list.
        """
        normalized = []
        seen = set()

        for tag in tags:
            if tag is None:
                continue
            tag = str(tag).lower().strip()
            if tag and tag not in seen:
                normalized.append(tag)
                seen.add(tag)

        # Limit to 10 tags
        return normalized[:10]

    def _apply_threshold_logic(
        self,
        parsed: ParsedResponse,
    ) -> ClassificationResult:
        """
        Apply confidence threshold logic and create final result.

        If confidence is below threshold and template is not already
        the fallback, switch to fallback template BUT preserve all
        extracted fields for potential use.

        Args:
            parsed: Validated parsed response.

        Returns:
            Final ClassificationResult.
        """
        template_name = parsed.template
        confidence = parsed.confidence

        # Check if we need to fall back due to low confidence
        if (
            confidence < self.confidence_threshold and
            template_name != self.fallback_template
        ):
            logger.info(
                f"Confidence {confidence:.2f} below threshold "
                f"{self.confidence_threshold}, falling back to "
                f"'{self.fallback_template}'"
            )

            # Get the fallback template to apply its defaults
            fallback = self.template_loader.get_template(self.fallback_template)

            # IMPORTANT: Preserve ALL extracted fields, not just those in fallback template
            # This ensures valuable data like priority, due_date, etc. is not lost
            preserved_fields = dict(parsed.fields)

            # Add any missing defaults from the fallback template
            if fallback:
                for field_config in fallback.fields:
                    if field_config.name not in preserved_fields:
                        if field_config.name == "summary" and parsed.fields:
                            # Generate summary from first non-empty field
                            for v in parsed.fields.values():
                                if v and isinstance(v, str):
                                    preserved_fields["summary"] = v[:500]
                                    break
                        elif field_config.default is not None:
                            preserved_fields[field_config.name] = field_config.default

            # Store original template suggestion in reasoning and in fields
            preserved_fields["_original_template"] = template_name
            reasoning = (
                f"Classified as '{template_name}' with confidence {confidence:.2f}, "
                f"but fell back to '{self.fallback_template}' due to low confidence. "
                f"Original reasoning: {parsed.reasoning or 'None provided'}"
            )

            return ClassificationResult(
                template_name=self.fallback_template,
                confidence=confidence,  # Keep original confidence for transparency
                fields=preserved_fields,
                title=parsed.title,
                tags=parsed.tags,
                reasoning=reasoning,
            )

        # No fallback needed
        return ClassificationResult(
            template_name=template_name,
            confidence=confidence,
            fields=parsed.fields,
            title=parsed.title,
            tags=parsed.tags,
            reasoning=parsed.reasoning,
        )


def create_fallback_result(
    transcript: str,
    reason: str = "Classification failed",
) -> ClassificationResult:
    """
    Create a fallback classification result when classification fails entirely.

    Attempts to extract useful fields from the transcript text even without
    LLM classification, including priority, due dates, and a cleaned title.

    Args:
        transcript: The original transcript text.
        reason: Reason for the fallback.

    Returns:
        ClassificationResult with general template and zero confidence.
    """
    # Generate cleaned title
    title = _generate_fallback_title(transcript)

    # Generate basic summary
    summary = transcript[:500] if len(transcript) > 500 else transcript

    # Build fields with whatever we can extract
    fields = {
        "summary": summary,
        "transcription": transcript,
    }

    # Extract priority from transcript text
    priority = _extract_priority_from_text(transcript)
    if priority:
        fields["priority"] = priority

    # Extract tags
    tags = _extract_fallback_tags(transcript)

    return ClassificationResult(
        template_name="general",
        confidence=0.0,
        fields=fields,
        title=title,
        tags=tags,
        reasoning=f"Fallback classification: {reason}",
    )


def _generate_fallback_title(transcript: str) -> str:
    """
    Generate a cleaned title from transcript text.

    Strips common meta-language prefixes and extracts the core content.

    Args:
        transcript: The transcript text.

    Returns:
        Cleaned title string.
    """
    if not transcript or not transcript.strip():
        return "Untitled capture"

    text = transcript.strip()

    # Try to find the core content by stripping meta-language prefixes
    # These patterns match common voice capture preambles
    meta_prefixes = [
        r"^this is a (?:high[- ]priority |low[- ]priority |urgent )?task\.?\s*",
        r"^this is an? (?:idea|thought|note|observation)\.?\s*",
        r"^(?:I need to|I have to|I've got to|I gotta)\s+",
        r"^(?:remind me to|don't forget to|remember to|make sure to)\s+",
        r"^(?:note to self|create a task|add a task|new task)\s*:?\s*",
    ]

    cleaned = text
    for pattern in meta_prefixes:
        new_text = re.sub(pattern, "", cleaned, count=1, flags=re.IGNORECASE)
        if new_text != cleaned:
            cleaned = new_text.strip()

    # Use the cleaned text or fall back to original
    if not cleaned:
        cleaned = text

    # Get first sentence from the cleaned text
    first_sentence = cleaned.split('.')[0].strip()
    if not first_sentence:
        first_sentence = cleaned[:60].strip()

    # Strip trailing deadline info for a cleaner title
    deadline_patterns = [
        r"\s+by\s+(?:this\s+)?(?:coming\s+)?(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday).*$",
        r"\s+by\s+(?:tomorrow|tonight|end of (?:day|week|month)).*$",
        r"\s+(?:before|until|due)\s+.*$",
    ]
    for pattern in deadline_patterns:
        first_sentence = re.sub(pattern, "", first_sentence, flags=re.IGNORECASE).strip()

    # Capitalize first letter
    if first_sentence and first_sentence[0].islower():
        first_sentence = first_sentence[0].upper() + first_sentence[1:]

    # Truncate if too long
    if len(first_sentence) > 60:
        title = first_sentence[:57] + "..."
    else:
        title = first_sentence or "Untitled capture"

    return title


def _extract_priority_from_text(transcript: str) -> Optional[str]:
    """
    Extract priority level from transcript text using keyword matching.

    Args:
        transcript: The transcript text.

    Returns:
        Priority string ("High", "Medium", "Low") or None if not detected.
    """
    text_lower = transcript.lower()

    high_keywords = [
        "high-priority", "high priority", "urgent", "asap",
        "critical", "important", "time-sensitive", "blocking",
        "immediately", "right away",
    ]
    low_keywords = [
        "low-priority", "low priority", "when you get a chance",
        "eventually", "nice to have", "backlog", "someday",
    ]

    for keyword in high_keywords:
        if keyword in text_lower:
            return "High"

    for keyword in low_keywords:
        if keyword in text_lower:
            return "Low"

    return None


def _extract_fallback_tags(transcript: str) -> List[str]:
    """
    Extract basic tags from transcript text.

    Args:
        transcript: The transcript text.

    Returns:
        List of tag strings.
    """
    text_lower = transcript.lower()
    tags = []

    # Check for common categories
    tag_keywords = {
        "personal": ["my", "i need", "i have to", "my car", "my truck"],
        "work": ["meeting", "client", "project", "deadline", "report"],
        "maintenance": ["fix", "repair", "replace", "broken", "brakes", "mechanic"],
        "urgent": ["urgent", "asap", "immediately", "right away", "critical"],
        "health": ["doctor", "appointment", "medication", "exercise", "gym"],
    }

    for tag, keywords in tag_keywords.items():
        for keyword in keywords:
            if keyword in text_lower:
                tags.append(tag)
                break

    return tags[:5]
