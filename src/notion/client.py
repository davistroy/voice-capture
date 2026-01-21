"""Notion API client service.

Handles all Notion API interactions for voice capture pages.
Implements retry logic with exponential backoff and rate limit handling.
"""

import asyncio
import random
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from notion_client import AsyncClient
from notion_client.errors import APIResponseError, HTTPResponseError

from src.notion.page_builder import PageBuilder
from src.models.transcription import TranscriptionResult

logger = logging.getLogger(__name__)


class NotionError(Exception):
    """Base exception for Notion operations."""
    pass


class NotionRateLimitError(NotionError):
    """Raised when Notion API rate limit is hit."""

    def __init__(self, message: str, retry_after: float = 1.0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class NotionPage:
    """Result from creating a Notion page.

    Attributes:
        id: The Notion page ID (UUID format).
        url: The URL to access the page in Notion.
    """
    id: str
    url: str


@dataclass
class CaptureMetadata:
    """Metadata about a voice capture for Notion page creation.

    Attributes:
        captured_at: Timestamp when audio was captured.
        device: Source device ("Watch", "Phone", or "Unknown").
        duration_seconds: Audio duration in seconds.
    """
    captured_at: datetime
    device: str
    duration_seconds: float


class NotionService:
    """Handles all Notion API interactions.

    Provides methods for creating voice capture pages in Notion databases
    with retry logic and rate limit handling.

    Args:
        api_key: Notion integration API key.
        database_id: Voice Captures database ID.
        max_retries: Maximum retry attempts (default 3).
        base_backoff: Base delay for exponential backoff in seconds (default 5.0).
        max_backoff: Maximum delay for exponential backoff in seconds (default 300.0).
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
        self._page_builder = PageBuilder()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def create_capture_page(
        self,
        transcription: TranscriptionResult,
        metadata: CaptureMetadata,
        title: Optional[str] = None,
    ) -> NotionPage:
        """Create a new page in the Voice Captures database.

        For Phase 1, creates pages with generic template only:
        - Title property: auto-generated from first sentence or provided
        - Date property: capture timestamp
        - Device property: Watch/Phone select
        - Type property: "General" select
        - Tags property: empty multi_select

        Page body includes:
        - Summary section (first 2-3 sentences)
        - Raw Transcript section
        - Processing metadata footer

        Args:
            transcription: The transcription result with text and duration.
            metadata: Capture metadata with timestamp, device, and duration.
            title: Optional custom title (defaults to first sentence).

        Returns:
            NotionPage with id and url on success.

        Raises:
            NotionError: On permanent failure after all retries.
            NotionRateLimitError: On rate limit with retry_after hint.
        """
        # Generate title from first sentence if not provided
        if not title:
            title = transcription.get_first_sentence(max_words=15)

        # Build the page properties and content
        properties = self._page_builder.build_properties(
            title=title,
            captured_at=metadata.captured_at,
            device=metadata.device,
            template_type="General",
            tags=[],
        )

        children = self._page_builder.build_page_content(
            transcript=transcription.text,
            captured_at=metadata.captured_at,
            device=metadata.device,
            duration_seconds=metadata.duration_seconds,
        )

        # Create the page with retry logic
        return await self._create_page_with_retry(properties, children)

    async def _create_page_with_retry(
        self,
        properties: Dict[str, Any],
        children: list[Dict[str, Any]],
    ) -> NotionPage:
        """Create a page with exponential backoff retry logic.

        Handles:
        - Rate limiting (HTTP 429) with Retry-After header
        - Server errors (5xx) with retry
        - Network errors with retry
        - Invalid request (4xx except 429) fails immediately

        Args:
            properties: Notion page properties dict.
            children: Notion page content blocks.

        Returns:
            NotionPage on success.

        Raises:
            NotionError: On permanent failure.
            NotionRateLimitError: On rate limit after max retries.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.pages.create(
                    parent={"database_id": self._database_id},
                    properties=properties,
                    children=children,
                )

                page_id = response["id"]
                page_url = response.get("url", f"https://notion.so/{page_id.replace('-', '')}")

                logger.info(f"Created Notion page: {page_id}")
                return NotionPage(id=page_id, url=page_url)

            except HTTPResponseError as e:
                last_error = e
                status = e.status

                # Rate limit - respect Retry-After header
                if status == 429:
                    retry_after = self._extract_retry_after(e)
                    logger.warning(f"Rate limited, retry after {retry_after}s (attempt {attempt + 1}/{self._max_retries + 1})")

                    if attempt < self._max_retries:
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        raise NotionRateLimitError(
                            f"Rate limited after {self._max_retries + 1} attempts",
                            retry_after=retry_after,
                        )

                # Server error (5xx) - retry with backoff
                elif status >= 500:
                    logger.warning(f"Server error {status}, retrying (attempt {attempt + 1}/{self._max_retries + 1})")
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._calculate_backoff(attempt))
                        continue
                    else:
                        raise NotionError(f"Server error after {self._max_retries + 1} attempts: {e}")

                # Client error (4xx except 429) - fail immediately
                else:
                    logger.error(f"Client error {status}: {e}")
                    raise NotionError(f"Client error: {e}")

            except APIResponseError as e:
                last_error = e
                logger.warning(f"API error, retrying (attempt {attempt + 1}/{self._max_retries + 1}): {e}")

                if attempt < self._max_retries:
                    await asyncio.sleep(self._calculate_backoff(attempt))
                    continue
                else:
                    raise NotionError(f"API error after {self._max_retries + 1} attempts: {e}")

            except Exception as e:
                last_error = e
                logger.warning(f"Network error, retrying (attempt {attempt + 1}/{self._max_retries + 1}): {e}")

                if attempt < self._max_retries:
                    await asyncio.sleep(self._calculate_backoff(attempt))
                    continue
                else:
                    raise NotionError(f"Network error after {self._max_retries + 1} attempts: {e}")

        # Should not reach here, but handle edge case
        raise NotionError(f"Unexpected failure: {last_error}")

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter.

        Formula: min(base * 2^attempt + jitter, max)
        Jitter is 10% of the calculated backoff.

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

        Falls back to 1.0 second if header is not present or invalid.

        Args:
            error: The HTTP response error.

        Returns:
            Retry delay in seconds.
        """
        try:
            # notion-client wraps the response, try to access headers
            if hasattr(error, 'response') and error.response:
                retry_after = error.response.headers.get('Retry-After', '1')
                return float(retry_after)
        except (AttributeError, ValueError, TypeError):
            pass

        # Default to 1 second if header not accessible
        return 1.0
