"""Synthesis prompt builder for weekly voice capture summaries.

Builds prompts for Claude to generate weekly synthesis from voice captures.
Implements the synthesis prompt structure per TDD section 13.2 and PRD section 8.2.

The prompt builder:
- Groups captures by template type
- Formats capture content for the LLM prompt
- Includes synthesis guidelines
- Specifies the output format matching the weekly summary template
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.synthesis.notion_query import VoiceCapture, group_by_template

logger = logging.getLogger(__name__)

# Template directory path
TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class CaptureStatistics:
    """Statistics about captures for a time period.

    Attributes:
        total_captures: Total number of captures.
        by_type: Count of captures by template type.
        total_duration_seconds: Total recording duration in seconds.
        supplemental_input_used: Whether supplemental input was provided.
    """
    total_captures: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    total_duration_seconds: float = 0.0
    supplemental_input_used: bool = False

    @property
    def total_duration_formatted(self) -> str:
        """Format total duration as human-readable string."""
        minutes = int(self.total_duration_seconds // 60)
        seconds = int(self.total_duration_seconds % 60)
        if minutes > 0:
            return f"{minutes} minute{'s' if minutes != 1 else ''} {seconds} second{'s' if seconds != 1 else ''}"
        return f"{seconds} second{'s' if seconds != 1 else ''}"


@dataclass
class IdeaReference:
    """Reference to an idea capture for linking in summary.

    Attributes:
        title: Idea title.
        url: Notion page URL.
        summary: Brief summary of the idea.
    """
    title: str
    url: str
    summary: str = ""


@dataclass
class WeeklySummaryData:
    """Data structure for weekly summary template rendering.

    Attributes:
        start_date: Start of the week (formatted string).
        end_date: End of the week (formatted string).
        overview: 2-3 sentence overview of the week.
        accomplishments: List of accomplishments.
        key_activities: Narrative of key activities.
        challenges: List of challenges and blockers.
        ideas: List of idea references with links.
        insights: Insights and reflections narrative.
        upcoming: List of upcoming items for next week.
        stats: Capture statistics.
    """
    start_date: str
    end_date: str
    overview: str = ""
    accomplishments: List[str] = field(default_factory=list)
    key_activities: str = ""
    challenges: List[str] = field(default_factory=list)
    ideas: List[IdeaReference] = field(default_factory=list)
    insights: str = ""
    upcoming: List[str] = field(default_factory=list)
    stats: CaptureStatistics = field(default_factory=CaptureStatistics)


class SynthesisPromptBuilder:
    """Builds synthesis prompts for weekly voice capture summaries.

    Constructs prompts that include:
    - Grouped captures by type
    - Synthesis guidelines per TDD section 13.2
    - Output format specification matching PRD section 8.2

    Args:
        templates_dir: Path to templates directory (default: module templates/).
    """

    # Ordered list of template types for consistent grouping
    TEMPLATE_TYPE_ORDER = [
        "Journal",
        "Task",
        "Idea",
        "Research",
        "Product",
        "General",
    ]

    def __init__(self, templates_dir: Optional[Path] = None):
        self._templates_dir = templates_dir or TEMPLATES_DIR
        self._jinja_env = Environment(
            loader=FileSystemLoader(self._templates_dir),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def build_synthesis_prompt(
        self,
        captures: List[VoiceCapture],
        start_date: datetime,
        end_date: datetime,
        supplemental_input: Optional[str] = None,
    ) -> str:
        """Build the synthesis prompt for weekly summary generation.

        Constructs a prompt that:
        1. Groups captures by template type
        2. Formats each capture with relevant details
        3. Includes synthesis guidelines
        4. Specifies the expected output format

        Args:
            captures: List of VoiceCapture objects for the week.
            start_date: Start of the synthesis period.
            end_date: End of the synthesis period.
            supplemental_input: Optional additional context from user.

        Returns:
            Complete prompt string for Claude.
        """
        # Group captures by type
        grouped = group_by_template(captures)

        # Calculate statistics
        stats = self._calculate_statistics(captures, grouped)
        if supplemental_input:
            stats.supplemental_input_used = True

        # Build prompt sections
        sections = [
            self._build_header(start_date, end_date, stats),
            self._build_captures_section(grouped),
        ]

        if supplemental_input:
            sections.append(self._build_supplemental_section(supplemental_input))

        sections.extend([
            self._build_guidelines_section(),
            self._build_output_format_section(),
        ])

        prompt = "\n\n".join(sections)

        logger.debug(f"Built synthesis prompt with {len(captures)} captures")
        return prompt

    def _build_header(
        self,
        start_date: datetime,
        end_date: datetime,
        stats: CaptureStatistics,
    ) -> str:
        """Build the prompt header with context information.

        Args:
            start_date: Start of synthesis period.
            end_date: End of synthesis period.
            stats: Capture statistics.

        Returns:
            Header section string.
        """
        date_range = f"{start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}"
        type_breakdown = ", ".join(
            f"{t}: {c}" for t, c in sorted(stats.by_type.items())
        )

        return f"""You are synthesizing a week's worth of voice captures into a reflection summary.

## Synthesis Context

- **Week:** {date_range}
- **Total Captures:** {stats.total_captures}
- **Breakdown by Type:** {type_breakdown if type_breakdown else "None"}
- **Total Recording Time:** {stats.total_duration_formatted}"""

    def _build_captures_section(
        self,
        grouped: Dict[str, List[VoiceCapture]],
    ) -> str:
        """Build the captures section grouped by type.

        Args:
            grouped: Captures grouped by template type.

        Returns:
            Captures section string.
        """
        if not grouped:
            return "## This Week's Captures\n\n*No captures found for this period.*"

        sections = ["## This Week's Captures"]

        # Process in consistent order
        for template_type in self.TEMPLATE_TYPE_ORDER:
            if template_type in grouped:
                type_captures = grouped[template_type]
                sections.append(
                    self._format_capture_group(template_type, type_captures)
                )

        # Handle any unexpected types
        for template_type, type_captures in grouped.items():
            if template_type not in self.TEMPLATE_TYPE_ORDER:
                sections.append(
                    self._format_capture_group(template_type, type_captures)
                )

        return "\n\n".join(sections)

    def _format_capture_group(
        self,
        template_type: str,
        captures: List[VoiceCapture],
    ) -> str:
        """Format a group of captures of the same type.

        Args:
            template_type: Type name (e.g., "Journal", "Task").
            captures: List of captures of this type.

        Returns:
            Formatted group string.
        """
        lines = [f"### {template_type} ({len(captures)})"]

        for capture in captures:
            lines.append(self._format_single_capture(capture))

        return "\n\n".join(lines)

    def _format_single_capture(self, capture: VoiceCapture) -> str:
        """Format a single capture for the prompt.

        Includes title, date, tags, and content in a structured format
        that's easy for the LLM to parse.

        Args:
            capture: VoiceCapture to format.

        Returns:
            Formatted capture string.
        """
        # Format date
        date_str = "Unknown date"
        if capture.captured_at:
            date_str = capture.captured_at.strftime("%B %d, %Y at %I:%M %p")

        # Format tags
        tags_str = ", ".join(capture.tags) if capture.tags else "none"

        # Build capture block
        lines = [
            f"**{capture.title}**",
            f"- Date: {date_str}",
            f"- Device: {capture.device}",
            f"- Tags: {tags_str}",
            f"- Notion URL: {capture.url}",
        ]

        # Include content if available
        if capture.content:
            # Truncate very long content
            content = capture.content
            if len(content) > 2000:
                content = content[:1997] + "..."
            lines.append(f"\nContent:\n```\n{content}\n```")

        return "\n".join(lines)

    def _build_supplemental_section(self, supplemental_input: str) -> str:
        """Build section for supplemental user input.

        Used when captures are sparse and user provides additional context.

        Args:
            supplemental_input: User-provided additional context.

        Returns:
            Supplemental input section string.
        """
        return f"""## Supplemental Input

The user provided additional context to supplement the captured voice notes:

```
{supplemental_input}
```

Please incorporate this information into the synthesis where relevant."""

    def _build_guidelines_section(self) -> str:
        """Build the synthesis guidelines section.

        Guidelines per TDD section 13.2 covering how to synthesize
        different aspects of the week's captures.

        Returns:
            Guidelines section string.
        """
        return """## Synthesis Guidelines

Follow these guidelines when generating the weekly summary:

1. **Overview**: Write 2-3 sentences summarizing the week's themes and focus areas. Identify the dominant threads across captures.

2. **Accomplishments**: Extract completed work, wins, and progress from Task and Journal entries. Focus on concrete achievements, not intentions.

3. **Key Activities**: Summarize significant meetings, work sessions, and decisions mentioned. Create a coherent narrative, not just a list.

4. **Challenges & Blockers**: Note any mentioned obstacles, frustrations, or unresolved issues. Include both explicit complaints and implicit struggles.

5. **Ideas Generated**: Highlight captured ideas with their Notion page links. Briefly note the core concept of each. Group related ideas if applicable.

6. **Insights & Reflections**: Identify patterns, lessons learned, and recurring themes across captures. Note any self-observations or realizations.

7. **Upcoming / Next Week**: Extract explicitly mentioned future plans and infer priorities based on open items, deadlines, and momentum.

8. **Statistics**: Include accurate counts and totals from the provided data.

**Important:**
- Maintain a reflective, personal tone appropriate for a weekly review
- Connect dots between captures where relevant relationships exist
- If supplemental input was provided, clearly integrate it but note in the summary that it was included
- Preserve links to original Notion pages for ideas and significant items
- Do not invent or fabricate information not present in the captures"""

    def _build_output_format_section(self) -> str:
        """Build the output format specification section.

        Specifies the exact JSON structure expected in the response.

        Returns:
            Output format section string.
        """
        return """## Output Format

Respond with valid JSON matching this structure:

```json
{
  "overview": "2-3 sentence summary of the week's themes",
  "accomplishments": [
    "First accomplishment",
    "Second accomplishment"
  ],
  "key_activities": "Narrative paragraph describing significant activities",
  "challenges": [
    "First challenge or blocker",
    "Second challenge"
  ],
  "ideas": [
    {
      "title": "Idea Title",
      "url": "https://notion.so/page-id",
      "summary": "Brief summary of the idea"
    }
  ],
  "insights": "Paragraph with patterns, lessons learned, reflections",
  "upcoming": [
    "First upcoming item",
    "Second upcoming item"
  ]
}
```

Ensure all arrays are present even if empty. The JSON must be valid and parseable."""

    def _calculate_statistics(
        self,
        captures: List[VoiceCapture],
        grouped: Dict[str, List[VoiceCapture]],
    ) -> CaptureStatistics:
        """Calculate statistics for the captures.

        Args:
            captures: All captures for the period.
            grouped: Captures grouped by type.

        Returns:
            CaptureStatistics with computed values.
        """
        stats = CaptureStatistics(
            total_captures=len(captures),
            by_type={t: len(c) for t, c in grouped.items()},
        )

        # Calculate total duration if available in properties
        total_duration = 0.0
        for capture in captures:
            # Try to extract duration from properties
            duration_prop = capture.properties.get("Duration", {})
            if duration_prop.get("type") == "number":
                duration_val = duration_prop.get("number")
                if duration_val is not None:
                    total_duration += float(duration_val)

        stats.total_duration_seconds = total_duration
        return stats

    def render_weekly_summary(self, data: WeeklySummaryData) -> str:
        """Render the weekly summary template with provided data.

        Uses the weekly_summary.md Jinja2 template.

        Args:
            data: WeeklySummaryData with all summary content.

        Returns:
            Rendered markdown summary.
        """
        template = self._jinja_env.get_template("weekly_summary.md")
        return template.render(
            start_date=data.start_date,
            end_date=data.end_date,
            overview=data.overview,
            accomplishments=data.accomplishments,
            key_activities=data.key_activities,
            challenges=data.challenges,
            ideas=data.ideas,
            insights=data.insights,
            upcoming=data.upcoming,
            stats=data.stats,
        )

    def format_captures_for_display(
        self,
        captures: List[VoiceCapture],
    ) -> str:
        """Format captures for display or logging.

        Creates a human-readable summary of captures.

        Args:
            captures: List of captures to format.

        Returns:
            Formatted string summary.
        """
        if not captures:
            return "No captures to display."

        grouped = group_by_template(captures)
        lines = [f"Total: {len(captures)} captures"]

        for template_type in self.TEMPLATE_TYPE_ORDER:
            if template_type in grouped:
                count = len(grouped[template_type])
                lines.append(f"  - {template_type}: {count}")

        return "\n".join(lines)


def build_synthesis_prompt(
    captures: List[VoiceCapture],
    start_date: datetime,
    end_date: datetime,
    supplemental_input: Optional[str] = None,
) -> str:
    """Convenience function to build synthesis prompt.

    Creates a SynthesisPromptBuilder and builds the prompt.

    Args:
        captures: List of VoiceCapture objects for the week.
        start_date: Start of the synthesis period.
        end_date: End of the synthesis period.
        supplemental_input: Optional additional context from user.

    Returns:
        Complete prompt string for Claude.
    """
    builder = SynthesisPromptBuilder()
    return builder.build_synthesis_prompt(
        captures=captures,
        start_date=start_date,
        end_date=end_date,
        supplemental_input=supplemental_input,
    )
