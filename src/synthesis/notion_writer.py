"""Notion writer for weekly synthesis summaries.

Creates weekly summary pages in the Weekly Summaries Notion database.
Handles page creation with proper properties, content blocks, and
links to source captures.

Implements TDD section 13.1 and PRD section 8.2 requirements.
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from notion_client import AsyncClient
from notion_client.errors import APIResponseError, HTTPResponseError

from src.synthesis.generator import SynthesisResult
from src.synthesis.prompt_builder import IdeaReference, WeeklySummaryData
from src.synthesis.notion_query import VoiceCapture

logger = logging.getLogger(__name__)


class NotionWriterError(Exception):
    """Base exception for Notion writer operations."""
    pass


class NotionWriterRateLimitError(NotionWriterError):
    """Raised when Notion API rate limit is hit."""

    def __init__(self, message: str, retry_after: float = 1.0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class SummaryPage:
    """Result from creating a summary page in Notion.

    Attributes:
        id: Notion page ID.
        url: URL to the Notion page.
        title: Page title.
        start_date: Start of synthesis period.
        end_date: End of synthesis period.
    """
    id: str
    url: str
    title: str
    start_date: str
    end_date: str


class NotionSummaryWriter:
    """Writes weekly synthesis summaries to Notion.

    Creates pages in the Weekly Summaries database with:
    - Title: "Week of {start_date} - {end_date}"
    - Date range properties
    - Full summary content as page body
    - Links to source captures where applicable

    Args:
        api_key: Notion integration API key.
        database_id: Weekly Summaries database ID.
        max_retries: Maximum retry attempts (default 3).
        base_backoff: Base delay for exponential backoff (default 5.0).
        max_backoff: Maximum delay for exponential backoff (default 300.0).
    """

    def __init__(
        self,
        api_key: str,
        database_id: str,
        max_retries: int = 3,
        base_backoff: float = 5.0,
        max_backoff: float = 300.0,
    ):
        self._client = AsyncClient(auth=api_key)
        self._database_id = database_id
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def create_summary_page(
        self,
        synthesis_result: SynthesisResult,
        source_captures: Optional[List[VoiceCapture]] = None,
    ) -> SummaryPage:
        """Create a weekly summary page in Notion.

        Creates a new page in the Weekly Summaries database with
        the synthesis results, including structured properties and
        full markdown content.

        Args:
            synthesis_result: SynthesisResult from generator.
            source_captures: Optional list of source captures for linking.

        Returns:
            SummaryPage with page ID and URL.

        Raises:
            NotionWriterError: On page creation failure.
        """
        # Build page title
        title = f"Week of {synthesis_result.summary_data.start_date} - {synthesis_result.summary_data.end_date}"

        # Build properties
        properties = self._build_properties(
            title=title,
            start_date=synthesis_result.start_date,
            end_date=synthesis_result.end_date,
            capture_count=synthesis_result.capture_count,
            supplemental_input_used=synthesis_result.supplemental_input_used,
        )

        # Build page content blocks
        children = self._build_page_content(
            summary_data=synthesis_result.summary_data,
            source_captures=source_captures,
        )

        # Create page with retry
        response = await self._create_page_with_retry(properties, children)

        page_id = response["id"]
        page_url = response.get("url", f"https://notion.so/{page_id.replace('-', '')}")

        logger.info(f"Created weekly summary page: {page_id}")

        return SummaryPage(
            id=page_id,
            url=page_url,
            title=title,
            start_date=synthesis_result.summary_data.start_date,
            end_date=synthesis_result.summary_data.end_date,
        )

    def _build_properties(
        self,
        title: str,
        start_date: datetime,
        end_date: datetime,
        capture_count: int,
        supplemental_input_used: bool,
    ) -> Dict[str, Any]:
        """Build Notion page properties.

        Args:
            title: Page title.
            start_date: Start of date range.
            end_date: End of date range.
            capture_count: Number of captures in synthesis.
            supplemental_input_used: Whether supplemental input was used.

        Returns:
            Dictionary of Notion property objects.
        """
        properties: Dict[str, Any] = {
            # Title property
            "Title": {
                "title": [
                    {
                        "text": {"content": title}
                    }
                ]
            },
            # Date range property
            "Date Range": {
                "date": {
                    "start": start_date.date().isoformat(),
                    "end": end_date.date().isoformat(),
                }
            },
            # Capture count property
            "Captures": {
                "number": capture_count
            },
        }

        # Add supplemental input indicator if used
        if supplemental_input_used:
            properties["Supplemental Input"] = {
                "checkbox": True
            }

        return properties

    def _build_page_content(
        self,
        summary_data: WeeklySummaryData,
        source_captures: Optional[List[VoiceCapture]] = None,
    ) -> List[Dict[str, Any]]:
        """Build Notion page content blocks from summary data.

        Creates the full page body with:
        - Overview section
        - Accomplishments list
        - Key Activities narrative
        - Challenges list
        - Ideas with links
        - Insights section
        - Upcoming items
        - Statistics
        - Source captures section (if provided)

        Args:
            summary_data: WeeklySummaryData with summary content.
            source_captures: Optional list of source captures.

        Returns:
            List of Notion block objects.
        """
        blocks: List[Dict[str, Any]] = []

        # Overview section
        blocks.append(self._heading_block("Overview"))
        blocks.append(self._paragraph_block(summary_data.overview or "No overview available."))

        # Accomplishments section
        blocks.append(self._heading_block("Accomplishments"))
        if summary_data.accomplishments:
            for item in summary_data.accomplishments:
                blocks.append(self._bulleted_list_block(item))
        else:
            blocks.append(self._italic_paragraph_block("No accomplishments captured this week"))

        # Key Activities section
        blocks.append(self._heading_block("Key Activities"))
        blocks.append(self._paragraph_block(summary_data.key_activities or "No key activities noted."))

        # Challenges section
        blocks.append(self._heading_block("Challenges & Blockers"))
        if summary_data.challenges:
            for item in summary_data.challenges:
                blocks.append(self._bulleted_list_block(item))
        else:
            blocks.append(self._italic_paragraph_block("No challenges noted this week"))

        # Ideas section with links
        blocks.append(self._heading_block("Ideas Generated"))
        if summary_data.ideas:
            for idea in summary_data.ideas:
                blocks.append(self._idea_block(idea))
        else:
            blocks.append(self._italic_paragraph_block("No ideas captured this week"))

        # Insights section
        blocks.append(self._heading_block("Insights & Reflections"))
        blocks.append(self._paragraph_block(summary_data.insights or "No insights noted."))

        # Upcoming section
        blocks.append(self._heading_block("Upcoming / Next Week"))
        if summary_data.upcoming:
            for item in summary_data.upcoming:
                blocks.append(self._bulleted_list_block(item))
        else:
            blocks.append(self._italic_paragraph_block("No upcoming items identified"))

        # Statistics section
        blocks.append(self._heading_block("Capture Statistics"))
        stats = summary_data.stats
        blocks.append(self._bulleted_list_block(f"Total captures: {stats.total_captures}"))

        # Type breakdown
        if stats.by_type:
            type_str = ", ".join(f"{t}({c})" for t, c in sorted(stats.by_type.items()))
            blocks.append(self._bulleted_list_block(f"By type: {type_str}"))

        blocks.append(self._bulleted_list_block(f"Total recording time: {stats.total_duration_formatted}"))
        blocks.append(self._bulleted_list_block(f"Date range: {summary_data.start_date} to {summary_data.end_date}"))

        # Divider
        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Source captures section
        if source_captures:
            blocks.append(self._heading_block("Source Captures"))
            for capture in source_captures:
                blocks.append(self._capture_link_block(capture))

        # Footer
        footer_text = f"Generated from {stats.total_captures} voice capture"
        if stats.total_captures != 1:
            footer_text += "s"
        if stats.supplemental_input_used:
            footer_text += " (includes supplemental input)"
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

        Handles Notion's 2000 character limit per rich_text element.

        Args:
            text: Paragraph text.

        Returns:
            Notion paragraph block object.
        """
        # Split long text into chunks
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
            Notion paragraph block with italic annotation.
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

    def _bulleted_list_block(self, text: str) -> Dict[str, Any]:
        """Create a bulleted list item block.

        Args:
            text: List item text.

        Returns:
            Notion bulleted_list_item block object.
        """
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": text}
                    }
                ]
            }
        }

    def _idea_block(self, idea: IdeaReference) -> Dict[str, Any]:
        """Create a bulleted list item for an idea with link.

        Args:
            idea: IdeaReference with title, URL, and summary.

        Returns:
            Notion bulleted_list_item block with link.
        """
        rich_text: List[Dict[str, Any]] = []

        # Title with link
        if idea.url:
            rich_text.append({
                "type": "text",
                "text": {
                    "content": idea.title,
                    "link": {"url": idea.url}
                }
            })
        else:
            rich_text.append({
                "type": "text",
                "text": {"content": idea.title}
            })

        # Summary if present
        if idea.summary:
            rich_text.append({
                "type": "text",
                "text": {"content": f": {idea.summary}"}
            })

        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": rich_text
            }
        }

    def _capture_link_block(self, capture: VoiceCapture) -> Dict[str, Any]:
        """Create a bulleted list item linking to a source capture.

        Args:
            capture: VoiceCapture to link.

        Returns:
            Notion bulleted_list_item block with link.
        """
        # Format date
        date_str = ""
        if capture.captured_at:
            date_str = f" ({capture.captured_at.strftime('%b %d')})"

        rich_text: List[Dict[str, Any]] = []

        # Type badge
        rich_text.append({
            "type": "text",
            "text": {"content": f"[{capture.template_type}] "}
        })

        # Title with link
        rich_text.append({
            "type": "text",
            "text": {
                "content": capture.title,
                "link": {"url": capture.url}
            }
        })

        # Date
        if date_str:
            rich_text.append({
                "type": "text",
                "text": {"content": date_str}
            })

        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": rich_text
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

    async def _create_page_with_retry(
        self,
        properties: Dict[str, Any],
        children: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create a page with exponential backoff retry logic.

        Args:
            properties: Notion page properties.
            children: Notion page content blocks.

        Returns:
            Notion API response.

        Raises:
            NotionWriterError: On permanent failure.
            NotionWriterRateLimitError: On rate limit after retries.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.pages.create(
                    parent={"database_id": self._database_id},
                    properties=properties,
                    children=children,
                )
                return response

            except HTTPResponseError as e:
                last_error = e
                status = e.status

                if status == 429:
                    retry_after = self._extract_retry_after(e)
                    logger.warning(
                        f"Rate limited, retry after {retry_after}s "
                        f"(attempt {attempt + 1}/{self._max_retries + 1})"
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        raise NotionWriterRateLimitError(
                            f"Rate limited after {self._max_retries + 1} attempts",
                            retry_after=retry_after,
                        )

                elif status >= 500:
                    logger.warning(
                        f"Server error {status}, retrying "
                        f"(attempt {attempt + 1}/{self._max_retries + 1})"
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._calculate_backoff(attempt))
                        continue
                    else:
                        raise NotionWriterError(
                            f"Server error after {self._max_retries + 1} attempts: {e}"
                        )

                else:
                    logger.error(f"Client error {status}: {e}")
                    raise NotionWriterError(f"Client error: {e}")

            except APIResponseError as e:
                last_error = e
                logger.warning(
                    f"API error, retrying "
                    f"(attempt {attempt + 1}/{self._max_retries + 1}): {e}"
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._calculate_backoff(attempt))
                    continue
                else:
                    raise NotionWriterError(
                        f"API error after {self._max_retries + 1} attempts: {e}"
                    )

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Network error, retrying "
                    f"(attempt {attempt + 1}/{self._max_retries + 1}): {e}"
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._calculate_backoff(attempt))
                    continue
                else:
                    raise NotionWriterError(
                        f"Network error after {self._max_retries + 1} attempts: {e}"
                    )

        raise NotionWriterError(f"Unexpected failure: {last_error}")

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter.

        Args:
            attempt: Current retry attempt (0-indexed).

        Returns:
            Backoff delay in seconds.
        """
        backoff = min(
            self._base_backoff * (2 ** attempt),
            self._max_backoff
        )
        # Add 10% jitter
        jitter = backoff * 0.1 * random.random()
        return backoff + jitter

    def _extract_retry_after(self, error: HTTPResponseError) -> float:
        """Extract Retry-After header value from rate limit response.

        Args:
            error: HTTP response error.

        Returns:
            Retry delay in seconds (default 1.0).
        """
        try:
            if hasattr(error, 'response') and error.response:
                retry_after = error.response.headers.get('Retry-After', '1')
                return float(retry_after)
        except (AttributeError, ValueError, TypeError):
            pass
        return 1.0


async def create_summary_page(
    api_key: str,
    database_id: str,
    synthesis_result: SynthesisResult,
    source_captures: Optional[List[VoiceCapture]] = None,
) -> SummaryPage:
    """Convenience function to create summary page without instantiating writer.

    Args:
        api_key: Notion integration API key.
        database_id: Weekly Summaries database ID.
        synthesis_result: SynthesisResult from generator.
        source_captures: Optional list of source captures for linking.

    Returns:
        SummaryPage with page ID and URL.

    Raises:
        NotionWriterError: On page creation failure.
    """
    writer = NotionSummaryWriter(api_key=api_key, database_id=database_id)
    try:
        return await writer.create_summary_page(
            synthesis_result=synthesis_result,
            source_captures=source_captures,
        )
    finally:
        await writer.close()
