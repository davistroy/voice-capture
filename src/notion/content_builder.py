"""Notion page content builder with Jinja2 template support.

Builds Notion page body content from Jinja2 templates defined in
template configurations. Handles template rendering, transcript
inclusion, and metadata footer generation.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from jinja2 import Environment, BaseLoader, TemplateSyntaxError, UndefinedError

logger = logging.getLogger(__name__)


# Maximum transcript length before truncation
MAX_TRANSCRIPT_LENGTH = 2000

# Truncation indicator
TRUNCATION_INDICATOR = "..."


class ContentBuildError(Exception):
    """Raised when content building fails."""
    pass


class ContentBuilder:
    """Builds Notion page content using Jinja2 templates.

    Renders page body templates from template configurations with
    classification fields, transcript, and metadata.
    """

    def __init__(self):
        """Initialize the content builder with Jinja2 environment."""
        # Jinja2 has a built-in 'default' filter that works well
        self._env = Environment(
            loader=BaseLoader(),
            autoescape=False,  # We're generating markdown, not HTML
        )

    def build_page_content(
        self,
        page_body_template: str,
        fields: Dict[str, Any],
        transcript: str,
        processed_at: datetime,
        device: str,
        duration_seconds: float,
    ) -> List[Dict[str, Any]]:
        """Build Notion page content blocks from Jinja2 template.

        The template is rendered with classification fields, then
        raw transcript and metadata footer are always appended.

        Args:
            page_body_template: Jinja2 template string from template config.
            fields: Extracted classification fields.
            transcript: Raw transcript text.
            processed_at: Processing timestamp.
            device: Source device name.
            duration_seconds: Audio duration.

        Returns:
            List of Notion block objects.

        Raises:
            ContentBuildError: If template rendering fails.
        """
        blocks: List[Dict[str, Any]] = []

        # Prepare template context
        context = self._prepare_context(
            fields=fields,
            transcript=transcript,
            processed_at=processed_at,
            device=device,
            duration_seconds=duration_seconds,
        )

        # Render the template
        try:
            rendered_content = self._render_template(page_body_template, context)
        except ContentBuildError:
            # If template rendering fails, fall back to basic structure
            logger.warning("Template rendering failed, using fallback structure")
            rendered_content = self._build_fallback_content(context)

        # Parse rendered markdown into Notion blocks
        content_blocks = self._markdown_to_blocks(rendered_content)
        blocks.extend(content_blocks)

        return blocks

    def build_basic_page_content(
        self,
        transcript: str,
        processed_at: datetime,
        device: str,
        duration_seconds: float,
        summary: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build basic page content without template (for generic template).

        Used when no Jinja2 template is available or for generic fallback.

        Args:
            transcript: Raw transcript text.
            processed_at: Processing timestamp.
            device: Source device name.
            duration_seconds: Audio duration.
            summary: Optional summary text.

        Returns:
            List of Notion block objects.
        """
        blocks: List[Dict[str, Any]] = []

        # Summary section
        blocks.append(self._heading_block("Summary"))
        if summary:
            summary_text = summary
        else:
            summary_text = self._extract_summary(transcript)
        blocks.append(self._paragraph_block(summary_text))

        # Raw Transcript section
        blocks.append(self._heading_block("Raw Transcript"))
        truncated_transcript = self._truncate_text(transcript, MAX_TRANSCRIPT_LENGTH)
        blocks.append(self._paragraph_block(truncated_transcript))

        # Divider
        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Metadata footer
        device_display = self._format_device_name(device)
        timestamp_str = processed_at.strftime("%Y-%m-%d %H:%M:%S")
        footer_text = f"Processed: {timestamp_str} | Device: {device_display} | Duration: {duration_seconds:.1f}s"
        blocks.append(self._italic_paragraph_block(footer_text))

        return blocks

    def _prepare_context(
        self,
        fields: Dict[str, Any],
        transcript: str,
        processed_at: datetime,
        device: str,
        duration_seconds: float,
    ) -> Dict[str, Any]:
        """Prepare template rendering context.

        Merges classification fields with standard metadata.

        Args:
            fields: Extracted classification fields.
            transcript: Raw transcript text.
            processed_at: Processing timestamp.
            device: Source device name.
            duration_seconds: Audio duration.

        Returns:
            Context dictionary for Jinja2 template.
        """
        # Start with classification fields
        context = dict(fields)

        # Add standard metadata
        context["transcript"] = transcript
        context["processed_at"] = processed_at.strftime("%Y-%m-%d %H:%M:%S")
        context["device"] = self._format_device_name(device)
        context["duration"] = f"{duration_seconds:.1f}"

        # Provide summary fallback if not in fields
        if "summary" not in context:
            context["summary"] = self._extract_summary(transcript)

        return context

    def _render_template(
        self,
        template_str: str,
        context: Dict[str, Any],
    ) -> str:
        """Render Jinja2 template with context.

        Args:
            template_str: Jinja2 template string.
            context: Template context variables.

        Returns:
            Rendered template string.

        Raises:
            ContentBuildError: If template rendering fails.
        """
        if not template_str or not template_str.strip():
            raise ContentBuildError("Empty template string")

        try:
            template = self._env.from_string(template_str)
            return template.render(**context)
        except TemplateSyntaxError as e:
            raise ContentBuildError(f"Template syntax error: {e}") from e
        except UndefinedError as e:
            raise ContentBuildError(f"Template variable error: {e}") from e
        except Exception as e:
            raise ContentBuildError(f"Template rendering failed: {e}") from e

    def _build_fallback_content(self, context: Dict[str, Any]) -> str:
        """Build fallback content when template rendering fails.

        Args:
            context: Template context with fields and metadata.

        Returns:
            Basic markdown content string.
        """
        parts = []

        # Summary
        summary = context.get("summary", "No summary available.")
        parts.append("## Summary")
        parts.append(summary)
        parts.append("")

        # Raw Transcript
        transcript = context.get("transcript", "")
        parts.append("## Raw Transcript")
        parts.append(transcript)
        parts.append("")

        # Footer
        parts.append("---")
        footer = f"*Processed: {context.get('processed_at', '')} | Device: {context.get('device', '')} | Duration: {context.get('duration', '')}s*"
        parts.append(footer)

        return "\n".join(parts)

    def _markdown_to_blocks(self, markdown: str) -> List[Dict[str, Any]]:
        """Convert markdown text to Notion blocks.

        Parses basic markdown syntax:
        - ## Heading -> heading_2
        - --- -> divider
        - *text* -> italic paragraph
        - Regular text -> paragraph

        Args:
            markdown: Markdown content string.

        Returns:
            List of Notion block objects.
        """
        blocks: List[Dict[str, Any]] = []
        lines = markdown.split("\n")

        current_paragraph: List[str] = []

        def flush_paragraph():
            """Flush accumulated paragraph lines to a block."""
            if current_paragraph:
                text = "\n".join(current_paragraph).strip()
                if text:
                    # Check if it's an italic paragraph (starts and ends with *)
                    if text.startswith("*") and text.endswith("*") and len(text) > 2:
                        blocks.append(self._italic_paragraph_block(text[1:-1]))
                    else:
                        blocks.append(self._paragraph_block(text))
                current_paragraph.clear()

        for line in lines:
            stripped = line.strip()

            # Heading
            if stripped.startswith("## "):
                flush_paragraph()
                heading_text = stripped[3:].strip()
                blocks.append(self._heading_block(heading_text))

            # Divider
            elif stripped == "---":
                flush_paragraph()
                blocks.append({"object": "block", "type": "divider", "divider": {}})

            # Empty line - could be paragraph break
            elif not stripped:
                flush_paragraph()

            # Regular text
            else:
                current_paragraph.append(line)

        # Flush any remaining paragraph
        flush_paragraph()

        return blocks

    def _heading_block(self, text: str) -> Dict[str, Any]:
        """Create a heading_2 block.

        Args:
            text: Heading text.

        Returns:
            Notion heading_2 block object.
        """
        return {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": text}
                    }
                ]
            }
        }

    def _paragraph_block(self, text: str) -> Dict[str, Any]:
        """Create a paragraph block.

        Handles Notion's 2000 character limit per rich_text element.

        Args:
            text: Paragraph text.

        Returns:
            Notion paragraph block object.
        """
        rich_text = self._split_to_rich_text(text)

        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": rich_text
            }
        }

    def _italic_paragraph_block(self, text: str) -> Dict[str, Any]:
        """Create a paragraph block with italic text.

        Args:
            text: Paragraph text to italicize.

        Returns:
            Notion paragraph block object with italic annotation.
        """
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": text},
                        "annotations": {"italic": True}
                    }
                ]
            }
        }

    def _split_to_rich_text(
        self,
        text: str,
        chunk_size: int = 2000,
    ) -> List[Dict[str, Any]]:
        """Split text into rich_text elements respecting Notion's limits.

        Args:
            text: Text to split.
            chunk_size: Maximum characters per element.

        Returns:
            List of Notion rich_text objects.
        """
        if not text or len(text) <= chunk_size:
            return [{"type": "text", "text": {"content": text or ""}}]

        rich_text = []
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            rich_text.append({"type": "text", "text": {"content": chunk}})

        return rich_text

    def _extract_summary(self, text: str, max_sentences: int = 3) -> str:
        """Extract first few sentences for summary.

        Args:
            text: Full transcript text.
            max_sentences: Maximum sentences to include.

        Returns:
            Summary text (first sentences or full text if short).
        """
        if not text:
            return "No transcript content."

        text = text.strip()

        # Split on sentence-ending punctuation
        sentences = []
        current = ""

        for char in text:
            current += char
            if char in ".!?":
                sentences.append(current.strip())
                current = ""
                if len(sentences) >= max_sentences:
                    break

        # Add any remaining text as final sentence
        if current.strip() and len(sentences) < max_sentences:
            sentences.append(current.strip())

        if not sentences:
            # No sentence markers found, return truncated text
            return text[:500] + ("..." if len(text) > 500 else "")

        return " ".join(sentences)

    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate text to maximum length with indicator.

        Args:
            text: Text to truncate.
            max_length: Maximum length including truncation indicator.

        Returns:
            Truncated text with "..." if needed.
        """
        if len(text) <= max_length:
            return text

        truncate_at = max_length - len(TRUNCATION_INDICATOR)
        return text[:truncate_at] + TRUNCATION_INDICATOR

    def _format_device_name(self, device: str) -> str:
        """Format device name for display.

        Capitalizes the device name. Allows any device name from the
        iOS shortcut to pass through.

        Args:
            device: Device value from capture metadata.

        Returns:
            Formatted device name with first letter capitalized.
        """
        stripped = device.strip() if device else ""
        return stripped.capitalize() if stripped else "Unknown"

