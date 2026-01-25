"""
Classification prompt builder.

Builds dynamic classification prompts from template definitions
and transcript metadata per TDD Section 4.3.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.classification.template_loader import TemplateLoader


@dataclass
class TranscriptMetadata:
    """
    Metadata about the transcript being classified.

    Attributes:
        captured_at: When the audio was captured.
        duration_seconds: Length of the recording in seconds.
        device: Source device (watch, phone, unknown).
    """
    captured_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    device: str = "unknown"

    def format_for_prompt(self) -> str:
        """
        Format metadata for inclusion in the classification prompt.

        Returns:
            Formatted string with metadata details.
        """
        lines = []

        if self.captured_at:
            lines.append(f"- Captured: {self.captured_at.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            lines.append("- Captured: Unknown time")

        if self.duration_seconds is not None:
            lines.append(f"- Duration: {self.duration_seconds:.1f} seconds")
        else:
            lines.append("- Duration: Unknown")

        lines.append(f"- Device: {self.device.capitalize()}")

        return "\n".join(lines)


class PromptBuilder:
    """
    Builds classification prompts from template definitions.

    Constructs the full prompt used for Claude classification,
    including template definitions, classification rules,
    transcript metadata, and response format specification.
    """

    def __init__(
        self,
        template_loader: TemplateLoader,
        system_context: str = "",
        confidence_threshold: float = 0.7,
    ):
        """
        Initialize the prompt builder.

        Args:
            template_loader: Loaded template configurations.
            system_context: Optional personalization context.
            confidence_threshold: Threshold for fallback to general.
        """
        self.template_loader = template_loader
        self.system_context = system_context.strip()
        self.confidence_threshold = confidence_threshold

    def build_classification_prompt(
        self,
        transcript: str,
        metadata: Optional[TranscriptMetadata] = None,
    ) -> str:
        """
        Build the full classification prompt.

        Args:
            transcript: The transcript text to classify.
            metadata: Optional metadata about the transcript.

        Returns:
            Complete prompt string for Claude API.
        """
        if metadata is None:
            metadata = TranscriptMetadata()

        sections = [
            self._build_system_section(),
            self._build_templates_section(),
            self._build_rules_section(),
            self._build_overlap_section(),
            self._build_metadata_section(metadata),
            self._build_transcript_section(transcript),
            self._build_response_format_section(),
        ]

        return "\n\n".join(section for section in sections if section)

    def _build_system_section(self) -> str:
        """Build the system context section."""
        base = (
            "You are classifying and structuring voice capture transcripts "
            "for a personal knowledge management system."
        )

        if self.system_context:
            return f"{base}\n\n{self.system_context}"
        return base

    def _build_templates_section(self) -> str:
        """Build the available templates section."""
        template_context = self.template_loader.build_classification_prompt_context()
        return f"## Available Templates\n\n{template_context}"

    def _build_rules_section(self) -> str:
        """Build the classification rules section."""
        return f"""## Classification Rules

1. Select the template that best matches the transcript content
2. Confidence should reflect how well the transcript fits the template:
   - 0.9-1.0: Perfect match, content clearly belongs to this template
   - 0.7-0.9: Good match, primary content fits the template
   - 0.5-0.7: Partial match, some content fits but ambiguous
   - Below 0.5: Poor match, content doesn't fit this template
3. If no template fits with confidence >= {self.confidence_threshold}, use "general"
4. Extract all relevant fields for the selected template
5. Generate a concise, descriptive title (5-15 words)
6. Generate 2-5 relevant topic tags"""

    def _build_overlap_section(self) -> str:
        """Build the overlap handling section."""
        return """## Overlap Handling

When content could fit multiple templates, use these guidelines:

- **Meeting with action items**: If primarily about the task, use Task; if primarily reflection, use Journal
- **Client work**: Classify by content type (Task, Idea, Product), not by client context
- **Learning while building**: If about the product, use Product; if broader learning, use Research
- **Ideas with tasks**: If there's a clear action item, use Task; if speculative, use Idea
- **Questions about topics**: If about specific learning goals, use Research; if about product features, use Product
- **General observations with feelings**: If emotionally reflective, use Journal; if neutral observations, use General"""

    def _build_metadata_section(self, metadata: TranscriptMetadata) -> str:
        """Build the transcript metadata section."""
        # Include current date so LLM can resolve relative dates
        from datetime import datetime
        current_date = datetime.now().strftime('%Y-%m-%d')
        current_weekday = datetime.now().strftime('%A')

        return f"""## Transcript Metadata

{metadata.format_for_prompt()}
- Current date: {current_date} ({current_weekday})"""

    def _build_transcript_section(self, transcript: str) -> str:
        """Build the transcript section."""
        # Clean up transcript for prompt
        clean_transcript = transcript.strip()

        return f'''## Transcript

"""
{clean_transcript}
"""'''

    def _build_response_format_section(self) -> str:
        """Build the response format specification section."""
        return """## Response Format

Respond with valid JSON only. Do not include any text before or after the JSON object.

{
  "template": "template_name",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of classification choice (1-2 sentences)",
  "title": "Suggested page title (5-15 words)",
  "tags": ["tag1", "tag2", "tag3"],
  "fields": {
    "field_name": "extracted_value",
    ...
  }
}

Important:
- The "template" must be one of the available template names or "general"
- The "confidence" must be a decimal between 0.0 and 1.0
- The "fields" object must include all required fields for the selected template
- Use null for optional fields that cannot be extracted from the transcript
- Tags should be lowercase, single words or hyphenated phrases
- CRITICAL: All date fields MUST be in ISO 8601 format (YYYY-MM-DD). Convert relative dates like "tomorrow", "next Friday", "next week" to actual dates using the current date provided in metadata. For example, if today is 2026-01-25 (Saturday) and the transcript says "next Friday", output "2026-01-30"."""


def build_corrective_prompt(original_response: str, error_message: str) -> str:
    """
    Build a corrective prompt when JSON parsing fails.

    Used to retry classification with guidance about the parsing error.

    Args:
        original_response: The response that failed to parse.
        error_message: The error encountered during parsing.

    Returns:
        Corrective prompt string.
    """
    return f"""Your previous response was not valid JSON. Please try again.

Error encountered: {error_message}

Your previous response:
{original_response[:500]}{"..." if len(original_response) > 500 else ""}

Please respond with ONLY a valid JSON object matching this exact structure:
{{
  "template": "template_name",
  "confidence": 0.85,
  "reasoning": "Brief explanation",
  "title": "Page title",
  "tags": ["tag1", "tag2"],
  "fields": {{
    "field_name": "value"
  }}
}}

Do not include any explanatory text, markdown formatting, or code blocks. Only the JSON object."""
