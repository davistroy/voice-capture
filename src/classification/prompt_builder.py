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

1. Select the template that best matches the transcript content. Look for explicit indicators:
   - "task", "to-do", "remind me", "need to", deadlines -> use "task" template
   - Reflections, feelings, mood -> use "journal" template
   - "idea", brainstorming, "what if" -> use "idea" template
   - "feedback on", "feedback for", "performance note" -> use "feedback" template
   - "quick update" within the first 12 words -> use "quick_update" template

2. **EXPLICIT TYPE DECLARATIONS** — If the transcript explicitly names its type, ALWAYS use that template with high confidence:
   - "quick update" appearing within the FIRST 12 WORDS of the transcript -> "quick_update" template, confidence 0.98+
     This takes HIGHEST PRIORITY. Check for "quick update" first before any other classification.
   - "This is a task", "high-priority task", "I have a task" -> "task" template, confidence 0.95+
   - "This is an idea", "here's an idea", "I had an idea" -> "idea" template, confidence 0.95+
   - "I want to research", "need to look into" -> "research" template, confidence 0.9+
   - "This is feedback", "feedback on [name]", "performance note on [name]" -> "feedback" template, confidence 0.95+
   - ANY mention of "task" combined with action items, deadlines, or priority -> "task" template, confidence 0.9+

3. Confidence should reflect how well the transcript fits the template:
   - 0.9-1.0: Perfect match, explicit template indicators present (e.g., user says "this is a task")
   - 0.7-0.9: Good match, content clearly fits the template
   - 0.5-0.7: Partial match, some content fits but ambiguous
   - Below 0.5: Poor match, content doesn't fit this template

4. If no template fits with confidence >= {self.confidence_threshold}, use "general"

5. IMPORTANT: Extract ALL fields defined for the selected template:
   - Read the "Extraction guidance" for each field
   - For priority: detect words like "high priority", "urgent", "ASAP" -> "High"
   - For due_date: convert relative dates ("next Friday") to YYYY-MM-DD format
   - For transcription: copy the COMPLETE original transcript text

6. Generate a clean title WITHOUT meta-language (no "Create a task", "Remind me to", "This is a")

7. Generate 2-5 relevant lowercase topic tags"""

    def _build_overlap_section(self) -> str:
        """Build the overlap handling section."""
        return """## Overlap Handling

When content could fit multiple templates, use these guidelines:

- **Meeting with action items**: If primarily about the task, use Task; if primarily reflection, use Journal
- **Client work**: Classify by content type (Task, Idea, Product), not by client context
- **Learning while building**: If about the product, use Product; if broader learning, use Research
- **Ideas with tasks**: If there's a clear action item, use Task; if speculative, use Idea
- **Questions about topics**: If about specific learning goals, use Research; if about product features, use Product
- **General observations with feelings**: If emotionally reflective, use Journal; if neutral observations, use General
- **Feedback vs Journal**: If about a specific employee's performance, use Feedback; if personal reflection on team dynamics, use Journal
- **Feedback vs Task**: If observing past performance, use Feedback; if assigning future action items to yourself, use Task
- **Quick Update vs Journal**: If "quick update" appears in the first 12 words and content reports on work status, use Quick Update; if purely reflective without work reporting, use Journal
- **Quick Update vs Task**: Quick Update reports on work already done or in progress; Task creates new action items to be done in the future"""

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
  "title": "Clean, concise page title (5-15 words)",
  "tags": ["tag1", "tag2", "tag3"],
  "fields": {
    "field_name": "extracted_value",
    ...
  }
}

CRITICAL INSTRUCTIONS:

1. **Title extraction**: The "title" MUST be a clean, concise summary of the CORE content.
   - STRIP all meta-language: "Create a task", "Remind me to", "Note to self", "I need to",
     "This is a", "This is a high-priority task", "I have a task to", etc.
   - STRIP priority and deadline info from the title (those go in separate fields)
   - Extract ONLY the actionable content as the title
   - Example: "This is a high-priority task. I need to get my truck brakes fixed by this coming Friday" -> "Get truck brakes fixed"
   - Example: "Create a high-priority task to get my truck brakes fixed" -> "Get truck brakes fixed"
   - Example: "Remind me to call John tomorrow" -> "Call John"
   - The title should describe WHAT, not HOW it was captured or what priority it has

2. **Field extraction**: You MUST extract ALL fields defined for the selected template.
   - Follow the "Extraction guidance" provided for each field
   - For select fields, use ONLY the allowed options listed
   - For date fields, convert relative dates to ISO 8601 format (YYYY-MM-DD) using the current date
   - Example: If today is 2026-01-25 (Saturday) and transcript says "this coming Friday", use "2026-01-30"
   - Example: If today is 2026-01-25 (Saturday) and transcript says "next Friday", use "2026-01-30"

3. **Priority extraction**: If the transcript contains "high priority", "high-priority", "urgent", "ASAP", "important" -> set priority to "High"

4. **Template selection**: Choose the template that best matches the content TYPE:
   - "task" for action items, to-dos, reminders (look for "need to", "have to", "remind me", deadlines, "task")
   - "journal" for reflections, feelings, daily observations
   - "idea" for brainstorming, speculative concepts
   - "research" for learning goals, topics to explore
   - "product" for features, bugs, product feedback
   - "feedback" for employee performance observations, commendations, improvement notes
   - "quick_update" for daily work status reports (look for "quick update" in the first 12 words)
   - "general" ONLY if content is truly ambiguous and does not match any other template
   - IMPORTANT: If "quick update" appears in the first 12 words, ALWAYS use "quick_update" template
   - IMPORTANT: If the user explicitly says "this is a task" or "high-priority task", ALWAYS use "task" template

5. **Required fields**: The "fields" object MUST include all fields marked [REQUIRED] for the selected template.

6. **Confidence**: Set to 0.95+ when the user explicitly names the content type (e.g., "this is a task").
   Set to 0.9+ if content clearly matches the template type with strong indicators.

7. **Employee feedback tags**: For the feedback template, the employee's first name MUST be the FIRST tag in the tags array."""


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
