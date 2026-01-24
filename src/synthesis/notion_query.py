"""Notion query module for weekly synthesis.

Provides functionality to query the Voice Captures database in Notion
for captures within a date range and group them by template type.

This module supports the Phase 4 weekly synthesis feature, enabling
retrieval of all captures from the last 7 days (or any date range)
for weekly reflection and summary generation.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from notion_client import AsyncClient
from notion_client.errors import APIResponseError, HTTPResponseError

from src.common.backoff import calculate_backoff

logger = logging.getLogger(__name__)


class NotionQueryError(Exception):
    """Base exception for Notion query operations."""
    pass


class NotionQueryRateLimitError(NotionQueryError):
    """Raised when Notion API rate limit is hit during query."""

    def __init__(self, message: str, retry_after: float = 1.0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class VoiceCapture:
    """Represents a voice capture retrieved from Notion.

    Attributes:
        id: Notion page ID.
        url: URL to the Notion page.
        title: Page title.
        captured_at: When the audio was captured.
        template_type: Template type (Journal, Task, Idea, etc.).
        device: Source device (Watch, Phone, Unknown).
        tags: List of tags assigned to the capture.
        content: Full page content (blocks as plain text).
        properties: Raw Notion properties dict.
    """
    id: str
    url: str
    title: str
    captured_at: Optional[datetime]
    template_type: str
    device: str
    tags: List[str] = field(default_factory=list)
    content: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)


class NotionQueryService:
    """Service for querying Notion Voice Captures database.

    Provides methods to retrieve captures by date range and group them
    by template type for weekly synthesis.

    Args:
        api_key: Notion integration API key.
        database_id: Voice Captures database ID.
        max_retries: Maximum retry attempts for API calls (default 3).
        page_size: Number of results per page for pagination (default 100).
    """

    # Maximum page size allowed by Notion API
    MAX_PAGE_SIZE = 100

    def __init__(
        self,
        api_key: str,
        database_id: str,
        max_retries: int = 3,
        page_size: int = 100,
    ):
        self._client = AsyncClient(auth=api_key)
        self._database_id = database_id
        self._max_retries = max_retries
        self._page_size = min(page_size, self.MAX_PAGE_SIZE)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def query_captures_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        include_content: bool = True,
    ) -> List[VoiceCapture]:
        """Query Voice Captures database for captures in a date range.

        Retrieves all captures where the Date property falls within the
        specified range (inclusive). Handles pagination automatically
        for large result sets.

        Args:
            start_date: Start of date range (inclusive).
            end_date: End of date range (inclusive).
            include_content: Whether to fetch page content blocks (default True).

        Returns:
            List of VoiceCapture objects sorted by captured_at ascending.

        Raises:
            NotionQueryError: On API errors after retries exhausted.
            NotionQueryRateLimitError: On rate limit after retries.
        """
        captures: List[VoiceCapture] = []
        has_more = True
        start_cursor: Optional[str] = None

        # Build the filter for date range query
        date_filter = self._build_date_range_filter(start_date, end_date)

        while has_more:
            # Query with pagination
            response = await self._query_database_with_retry(
                filter_params=date_filter,
                start_cursor=start_cursor,
            )

            # Process results
            for page in response.get("results", []):
                capture = self._parse_capture_from_page(page)

                # Optionally fetch full page content
                if include_content:
                    capture.content = await self._fetch_page_content(page["id"])

                captures.append(capture)

            # Check for more pages
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

        # Sort by captured_at ascending
        captures.sort(key=lambda c: c.captured_at or datetime.min)

        logger.info(
            f"Retrieved {len(captures)} captures from {start_date.date()} to {end_date.date()}"
        )

        return captures

    async def query_last_n_days(
        self,
        days: int = 7,
        include_content: bool = True,
    ) -> List[VoiceCapture]:
        """Query captures from the last N days.

        Convenience method that calculates the date range from today
        going back N days.

        Args:
            days: Number of days to look back (default 7).
            include_content: Whether to fetch page content blocks.

        Returns:
            List of VoiceCapture objects.
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        return await self.query_captures_by_date_range(
            start_date=start_date,
            end_date=end_date,
            include_content=include_content,
        )

    def _build_date_range_filter(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """Build Notion filter for date range query.

        Uses the Date property with on_or_after and on_or_before conditions.

        Args:
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            Notion filter dictionary.
        """
        return {
            "and": [
                {
                    "property": "Date",
                    "date": {
                        "on_or_after": start_date.date().isoformat()
                    }
                },
                {
                    "property": "Date",
                    "date": {
                        "on_or_before": end_date.date().isoformat()
                    }
                }
            ]
        }

    async def _query_database_with_retry(
        self,
        filter_params: Dict[str, Any],
        start_cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query database with retry logic for transient failures.

        Args:
            filter_params: Notion filter parameters.
            start_cursor: Pagination cursor from previous query.

        Returns:
            Notion API response dictionary.

        Raises:
            NotionQueryError: On permanent failure.
            NotionQueryRateLimitError: On rate limit after retries.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                query_params: Dict[str, Any] = {
                    "database_id": self._database_id,
                    "filter": filter_params,
                    "page_size": self._page_size,
                    "sorts": [
                        {
                            "property": "Date",
                            "direction": "ascending"
                        }
                    ]
                }

                if start_cursor:
                    query_params["start_cursor"] = start_cursor

                response = await self._client.databases.query(**query_params)
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
                        raise NotionQueryRateLimitError(
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
                        raise NotionQueryError(
                            f"Server error after {self._max_retries + 1} attempts: {e}"
                        )

                else:
                    logger.error(f"Client error {status}: {e}")
                    raise NotionQueryError(f"Client error: {e}")

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
                    raise NotionQueryError(
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
                    raise NotionQueryError(
                        f"Network error after {self._max_retries + 1} attempts: {e}"
                    )

        raise NotionQueryError(f"Unexpected failure: {last_error}")

    def _parse_capture_from_page(self, page: Dict[str, Any]) -> VoiceCapture:
        """Parse a Notion page response into a VoiceCapture object.

        Extracts standard properties: Title, Date, Type, Device, Tags.

        Args:
            page: Notion page object from API response.

        Returns:
            VoiceCapture with extracted properties.
        """
        properties = page.get("properties", {})

        # Extract title
        title = self._extract_title(properties)

        # Extract date
        captured_at = self._extract_date(properties, "Date")

        # Extract Type (template)
        template_type = self._extract_select(properties, "Type") or "General"

        # Extract Device
        device = self._extract_select(properties, "Device") or "Unknown"

        # Extract Tags
        tags = self._extract_multi_select(properties, "Tags")

        # Build URL from page ID
        page_id = page["id"]
        url = page.get("url", f"https://notion.so/{page_id.replace('-', '')}")

        return VoiceCapture(
            id=page_id,
            url=url,
            title=title,
            captured_at=captured_at,
            template_type=template_type,
            device=device,
            tags=tags,
            content="",  # Will be populated later if requested
            properties=properties,
        )

    def _extract_title(self, properties: Dict[str, Any]) -> str:
        """Extract title from properties.

        Tries common title property names: Title, Name, Task.

        Args:
            properties: Notion properties dictionary.

        Returns:
            Title string or "Untitled" if not found.
        """
        for title_key in ["Title", "Name", "Task"]:
            if title_key in properties:
                title_prop = properties[title_key]
                if title_prop.get("type") == "title":
                    title_items = title_prop.get("title", [])
                    if title_items:
                        return "".join(
                            item.get("plain_text", "")
                            for item in title_items
                        )
        return "Untitled"

    def _extract_date(
        self,
        properties: Dict[str, Any],
        property_name: str,
    ) -> Optional[datetime]:
        """Extract date from a date property.

        Args:
            properties: Notion properties dictionary.
            property_name: Name of the date property.

        Returns:
            datetime or None if not found.
        """
        prop = properties.get(property_name, {})
        if prop.get("type") == "date":
            date_obj = prop.get("date")
            if date_obj and date_obj.get("start"):
                date_str = date_obj["start"]
                try:
                    # Handle both date and datetime formats
                    if "T" in date_str:
                        # Has time component
                        if date_str.endswith("Z"):
                            date_str = date_str[:-1] + "+00:00"
                        return datetime.fromisoformat(date_str)
                    else:
                        # Date only
                        return datetime.fromisoformat(date_str)
                except ValueError:
                    logger.warning(f"Could not parse date: {date_str}")
        return None

    def _extract_select(
        self,
        properties: Dict[str, Any],
        property_name: str,
    ) -> Optional[str]:
        """Extract value from a select property.

        Args:
            properties: Notion properties dictionary.
            property_name: Name of the select property.

        Returns:
            Selected option name or None.
        """
        prop = properties.get(property_name, {})
        if prop.get("type") == "select":
            select_obj = prop.get("select")
            if select_obj:
                return select_obj.get("name")
        return None

    def _extract_multi_select(
        self,
        properties: Dict[str, Any],
        property_name: str,
    ) -> List[str]:
        """Extract values from a multi_select property.

        Args:
            properties: Notion properties dictionary.
            property_name: Name of the multi_select property.

        Returns:
            List of selected option names.
        """
        prop = properties.get(property_name, {})
        if prop.get("type") == "multi_select":
            options = prop.get("multi_select", [])
            return [opt.get("name", "") for opt in options if opt.get("name")]
        return []

    async def _fetch_page_content(self, page_id: str) -> str:
        """Fetch and concatenate page content blocks as plain text.

        Retrieves all blocks from a page and extracts their text content.
        Handles pagination for pages with many blocks.

        Args:
            page_id: Notion page ID.

        Returns:
            Plain text content of the page.
        """
        content_parts: List[str] = []
        has_more = True
        start_cursor: Optional[str] = None

        try:
            while has_more:
                params: Dict[str, Any] = {
                    "block_id": page_id,
                    "page_size": self._page_size,
                }
                if start_cursor:
                    params["start_cursor"] = start_cursor

                response = await self._client.blocks.children.list(**params)

                for block in response.get("results", []):
                    block_text = self._extract_block_text(block)
                    if block_text:
                        content_parts.append(block_text)

                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor")

        except Exception as e:
            logger.warning(f"Could not fetch content for page {page_id}: {e}")
            return ""

        return "\n".join(content_parts)

    def _extract_block_text(self, block: Dict[str, Any]) -> str:
        """Extract plain text from a Notion block.

        Handles common block types: paragraph, heading_1/2/3, bulleted_list_item,
        numbered_list_item, toggle, quote, callout.

        Args:
            block: Notion block object.

        Returns:
            Plain text content or empty string.
        """
        block_type = block.get("type", "")

        # Block types that contain rich_text arrays
        text_block_types = [
            "paragraph",
            "heading_1",
            "heading_2",
            "heading_3",
            "bulleted_list_item",
            "numbered_list_item",
            "toggle",
            "quote",
            "callout",
        ]

        if block_type in text_block_types:
            block_content = block.get(block_type, {})
            rich_text = block_content.get("rich_text", [])
            text = "".join(
                item.get("plain_text", "")
                for item in rich_text
            )

            # Add prefix for headings
            if block_type == "heading_1":
                text = f"# {text}"
            elif block_type == "heading_2":
                text = f"## {text}"
            elif block_type == "heading_3":
                text = f"### {text}"
            elif block_type == "bulleted_list_item":
                text = f"- {text}"
            elif block_type == "numbered_list_item":
                text = f"1. {text}"
            elif block_type == "quote":
                text = f"> {text}"

            return text

        return ""

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay.

        Delegates to src.common.backoff.calculate_backoff.

        Args:
            attempt: Current retry attempt (0-indexed).

        Returns:
            Backoff delay in seconds.
        """
        return calculate_backoff(
            attempt=attempt,
            base_seconds=5.0,
            max_seconds=300.0,
            multiplier=2.0,
            jitter_factor=0.1,
        )

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


def group_by_template(captures: List[VoiceCapture]) -> Dict[str, List[VoiceCapture]]:
    """Group captures by their template type.

    Creates a dictionary mapping template type names to lists of captures
    of that type. Useful for organizing captures for weekly synthesis.

    Args:
        captures: List of VoiceCapture objects.

    Returns:
        Dictionary mapping template type (e.g., "Journal", "Task") to
        list of captures of that type.
    """
    grouped: Dict[str, List[VoiceCapture]] = {}

    for capture in captures:
        template_type = capture.template_type or "General"
        if template_type not in grouped:
            grouped[template_type] = []
        grouped[template_type].append(capture)

    # Log the grouping results
    logger.debug(
        f"Grouped {len(captures)} captures into {len(grouped)} template types: "
        f"{', '.join(f'{k}({len(v)})' for k, v in grouped.items())}"
    )

    return grouped


async def query_captures_by_date_range(
    api_key: str,
    database_id: str,
    start_date: datetime,
    end_date: datetime,
    include_content: bool = True,
) -> List[VoiceCapture]:
    """Convenience function to query captures without instantiating service.

    Creates a NotionQueryService, queries captures, and closes the client.

    Args:
        api_key: Notion integration API key.
        database_id: Voice Captures database ID.
        start_date: Start of date range (inclusive).
        end_date: End of date range (inclusive).
        include_content: Whether to fetch page content blocks.

    Returns:
        List of VoiceCapture objects.

    Raises:
        NotionQueryError: On API errors.
    """
    service = NotionQueryService(api_key=api_key, database_id=database_id)
    try:
        return await service.query_captures_by_date_range(
            start_date=start_date,
            end_date=end_date,
            include_content=include_content,
        )
    finally:
        await service.close()
