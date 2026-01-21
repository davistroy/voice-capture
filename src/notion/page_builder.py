"""Notion page content builder.

Builds Notion page properties and content blocks for voice capture pages.
Handles transcript truncation and metadata formatting.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


# Maximum transcript length before truncation
MAX_TRANSCRIPT_LENGTH = 2000

# Truncation indicator
TRUNCATION_INDICATOR = "..."


class PageBuilder:
    """Builds Notion page properties and content blocks.

    Handles the conversion of voice capture data into Notion API format,
    including transcript truncation and formatting.
    """

    def build_properties(
        self,
        title: str,
        captured_at: datetime,
        device: str,
        template_type: str = "General",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build Notion page properties for a voice capture.

        Creates properties for the generic template:
        - Title: Page title (from first sentence or provided)
        - Date: Capture timestamp
        - Device: Watch/Phone/Unknown select
        - Type: Template type select (General for Phase 1)
        - Tags: Multi-select tags (empty for Phase 1)

        Args:
            title: Page title text.
            captured_at: Capture timestamp.
            device: Source device name.
            template_type: Template type (default "General").
            tags: List of tag strings (default empty).

        Returns:
            Dict of Notion property objects.
        """
        if tags is None:
            tags = []

        # Map device string to proper display format
        device_display = self._format_device_name(device)

        properties: Dict[str, Any] = {
            "Title": {
                "title": [
                    {
                        "text": {
                            "content": title
                        }
                    }
                ]
            },
            "Date": {
                "date": {
                    "start": captured_at.isoformat()
                }
            },
            "Device": {
                "select": {
                    "name": device_display
                }
            },
            "Type": {
                "select": {
                    "name": template_type
                }
            },
            "Tags": {
                "multi_select": [{"name": tag} for tag in tags]
            },
        }

        return properties

    def build_page_content(
        self,
        transcript: str,
        captured_at: datetime,
        device: str,
        duration_seconds: float,
        summary: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build Notion page content blocks.

        Creates the page body with structure:
        - ## Summary (first 2-3 sentences if no summary provided)
        - ## Raw Transcript (full or truncated transcript)
        - --- (divider)
        - Processing metadata footer

        Args:
            transcript: The full transcript text.
            captured_at: Capture timestamp.
            device: Source device name.
            duration_seconds: Audio duration in seconds.
            summary: Optional custom summary (defaults to first sentences).

        Returns:
            List of Notion block objects.
        """
        blocks: List[Dict[str, Any]] = []

        # Summary section
        blocks.append(self._heading_block("Summary"))

        # Use provided summary or extract from transcript
        if summary:
            summary_text = summary
        else:
            summary_text = self._extract_summary(transcript)

        blocks.append(self._paragraph_block(summary_text))

        # Raw Transcript section
        blocks.append(self._heading_block("Raw Transcript"))

        # Truncate transcript if too long
        truncated_transcript = self._truncate_text(transcript, MAX_TRANSCRIPT_LENGTH)
        blocks.append(self._paragraph_block(truncated_transcript))

        # Divider
        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Metadata footer
        device_display = self._format_device_name(device)
        timestamp_str = captured_at.strftime("%Y-%m-%d %H:%M:%S")
        footer_text = f"Processed: {timestamp_str} | Device: {device_display} | Duration: {duration_seconds:.1f}s"

        blocks.append(self._italic_paragraph_block(footer_text))

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

        Handles Notion's 2000 character limit per rich_text element
        by splitting long text into multiple elements.

        Args:
            text: Paragraph text.

        Returns:
            Notion paragraph block object.
        """
        # Notion has a 2000 char limit per rich_text element
        # Split into chunks if needed
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
        chunk_size: int = 2000
    ) -> List[Dict[str, Any]]:
        """Split text into rich_text elements respecting Notion's limits.

        Notion has a 2000 character limit per rich_text element.
        This method splits longer text into multiple elements.

        Args:
            text: Text to split.
            chunk_size: Maximum characters per element.

        Returns:
            List of Notion rich_text objects.
        """
        if len(text) <= chunk_size:
            return [{"type": "text", "text": {"content": text}}]

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
                # Check if this looks like end of sentence (followed by space or end)
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

        # Account for truncation indicator length
        truncate_at = max_length - len(TRUNCATION_INDICATOR)
        return text[:truncate_at] + TRUNCATION_INDICATOR

    def _format_device_name(self, device: str) -> str:
        """Format device name for Notion select property.

        Converts internal device values to display format:
        - "watch" -> "Watch"
        - "phone" -> "Phone"
        - "unknown" -> "Unknown"

        Args:
            device: Device value (lowercase or any case).

        Returns:
            Formatted device name with title case.
        """
        device_lower = device.lower()
        if device_lower == "watch":
            return "Watch"
        elif device_lower == "phone":
            return "Phone"
        else:
            return "Unknown"
