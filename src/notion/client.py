"""Notion API client service.

Handles all Notion API interactions for voice capture pages.
Implements retry logic with exponential backoff and rate limit handling.

Phase 2 enhancement: Supports template-specific property mapping
via PropertyMapper and Jinja2 content building via ContentBuilder.

Preferred instantiation pattern:
    # Using factory method (recommended)
    from src.config.settings import get_settings
    settings = get_settings()
    service = NotionService.from_settings(settings)

    # Direct instantiation (for testing or custom configuration)
    service = NotionService(
        api_key="...",
        database_id="...",
        max_retries=3,
    )
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from notion_client import AsyncClient

from src.common.backoff import calculate_backoff
from notion_client.errors import APIResponseError, HTTPResponseError

from src.notion.page_builder import PageBuilder
from src.notion.property_mapper import (
    PropertyMapper,
    PropertyMappingError,
    create_device_property,
    create_location_property,
    create_rich_text_property,
    create_type_property,
)
from src.notion.content_builder import ContentBuilder, ContentBuildError
from src.models.transcription import TranscriptionResult
from src.models.classification import ClassificationResult
from src.classification.template_config import FieldConfig, FieldType, TemplateConfig

if TYPE_CHECKING:
    from src.config.settings import Settings

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
        location: Optional location string from capture source.
    """
    captured_at: datetime
    device: str
    duration_seconds: float
    location: Optional[str] = None


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
        self._property_mapper = PropertyMapper()
        self._content_builder = ContentBuilder()
        self._known_properties: Optional[set] = None

    @classmethod
    def from_settings(cls, settings: Settings) -> NotionService:
        """
        Create a NotionService from application settings.

        This is the preferred way to instantiate the service in production code.
        It extracts all necessary configuration from the Settings object.

        Args:
            settings: Application settings containing Notion API key, database ID,
                and pipeline configuration.

        Returns:
            Configured NotionService instance.

        Example:
            from src.config.settings import get_settings
            settings = get_settings()
            service = NotionService.from_settings(settings)
        """
        return cls(
            api_key=settings.notion_api_key,
            database_id=settings.notion_voice_captures_db_id,
            max_retries=settings.pipeline.max_retries,
            base_backoff=settings.pipeline.base_backoff_seconds,
            max_backoff=settings.pipeline.max_backoff_seconds,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def create_capture_page(
        self,
        transcription: TranscriptionResult,
        metadata: CaptureMetadata,
        title: Optional[str] = None,
        classification: Optional[ClassificationResult] = None,
        template: Optional[TemplateConfig] = None,
    ) -> NotionPage:
        """Create a new page in the Voice Captures database.

        When classification and template are provided (Phase 2+), creates
        template-specific pages with extracted fields mapped to Notion
        properties and Jinja2-rendered page body.

        When not provided (Phase 1), creates pages with generic template only.

        Args:
            transcription: The transcription result with text and duration.
            metadata: Capture metadata with timestamp, device, and duration.
            title: Optional custom title (defaults to classification title or first sentence).
            classification: Optional classification result with template and fields.
            template: Optional template configuration for property mapping.

        Returns:
            NotionPage with id and url on success.

        Raises:
            NotionError: On permanent failure after all retries.
            NotionRateLimitError: On rate limit with retry_after hint.
        """
        # Determine which creation path to use
        if classification is not None and template is not None:
            return await self._create_template_page(
                transcription=transcription,
                metadata=metadata,
                classification=classification,
                template=template,
                title_override=title,
            )
        else:
            # Fall back to basic page creation (Phase 1 behavior)
            return await self._create_basic_page(
                transcription=transcription,
                metadata=metadata,
                title=title,
            )

    async def _create_basic_page(
        self,
        transcription: TranscriptionResult,
        metadata: CaptureMetadata,
        title: Optional[str] = None,
    ) -> NotionPage:
        """Create a basic page with generic template (Phase 1 behavior).

        Args:
            transcription: The transcription result.
            metadata: Capture metadata.
            title: Optional custom title.

        Returns:
            NotionPage with id and url.
        """
        # Generate title from first sentence if not provided
        if not title:
            title = transcription.get_first_sentence(max_words=15)

        # Build the page properties and content using legacy page builder
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

        return await self._create_page_with_retry(properties, children)

    async def _create_template_page(
        self,
        transcription: TranscriptionResult,
        metadata: CaptureMetadata,
        classification: ClassificationResult,
        template: TemplateConfig,
        title_override: Optional[str] = None,
    ) -> NotionPage:
        """Create a template-specific page with extracted fields (Phase 2+).

        Maps classification fields to Notion properties using PropertyMapper
        and renders page body using ContentBuilder with Jinja2 template.

        Args:
            transcription: The transcription result.
            metadata: Capture metadata.
            classification: Classification result with template and fields.
            template: Template configuration.
            title_override: Optional title override.

        Returns:
            NotionPage with id and url.
        """
        # Ensure database has all required properties
        await self._ensure_database_properties(template)

        # Build properties from template fields
        properties = self._build_template_properties(
            classification=classification,
            template=template,
            metadata=metadata,
            transcription=transcription,
            title_override=title_override,
        )

        # Build page content using Jinja2 template
        children = self._build_template_content(
            classification=classification,
            template=template,
            transcription=transcription,
            metadata=metadata,
        )

        return await self._create_page_with_retry(properties, children)

    def _build_template_properties(
        self,
        classification: ClassificationResult,
        template: TemplateConfig,
        metadata: CaptureMetadata,
        transcription: TranscriptionResult,
        title_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build Notion properties from template field configuration.

        Maps extracted fields to Notion properties using the property mapper.
        Adds standard properties: Device, Type, Transcription, and ensures
        Title is set.

        Args:
            classification: Classification result with extracted fields.
            template: Template configuration with field definitions.
            metadata: Capture metadata.
            transcription: Transcription result for standard Transcription property.
            title_override: Optional title override.

        Returns:
            Dictionary of Notion property objects.
        """
        properties: Dict[str, Any] = {}

        # Map extracted fields to properties
        try:
            field_properties = self._property_mapper.map_fields_to_properties(
                fields=classification.fields,
                field_configs=template.fields,
                apply_defaults=True,
            )
            properties.update(field_properties)
        except PropertyMappingError as e:
            logger.warning(f"Property mapping error: {e}")

        # Ensure Title property is set
        title = title_override or classification.title
        if not title:
            title = "Untitled Capture"
        # Find title field config to get the correct property name
        title_property_name = "Title"
        for field_config in template.fields:
            if field_config.type.value == "title" and field_config.get_notion_property_name():
                title_property_name = field_config.get_notion_property_name()
                break
        properties[title_property_name] = {
            "title": [{"text": {"content": title}}]
        }

        # Add Device property
        properties["Device"] = create_device_property(metadata.device)

        # Add Location property if available
        if metadata.location:
            properties["Location"] = create_location_property(metadata.location)

        # Add Type property (uses template display name)
        properties["Type"] = create_type_property(template.display_name)

        # Add Tags property from classification
        if classification.tags:
            properties["Tags"] = {
                "multi_select": [{"name": tag} for tag in classification.tags]
            }
        elif "Tags" not in properties:
            properties["Tags"] = {"multi_select": []}

        # Add Date property if not already set from fields
        if "Date" not in properties:
            # Find date field config to get the correct property name
            date_property_name = "Date"
            for field_config in template.fields:
                prop_name = field_config.get_notion_property_name()
                if field_config.type.value == "date" and prop_name and "created" in field_config.name.lower():
                    date_property_name = prop_name
                    break
            properties[date_property_name] = {
                "date": {"start": metadata.captured_at.isoformat()}
            }

        # Ensure Transcription property is always set from raw transcript
        if "Transcription" not in properties:
            properties["Transcription"] = create_rich_text_property(
                transcription.text or ""
            )

        return properties

    def _build_template_content(
        self,
        classification: ClassificationResult,
        template: TemplateConfig,
        transcription: TranscriptionResult,
        metadata: CaptureMetadata,
    ) -> List[Dict[str, Any]]:
        """Build page content blocks from template's Jinja2 template.

        Args:
            classification: Classification result with extracted fields.
            template: Template configuration with page_body_template.
            transcription: Transcription result.
            metadata: Capture metadata.

        Returns:
            List of Notion block objects.
        """
        # Use content builder if template has a page_body_template
        if template.page_body_template and template.page_body_template.strip():
            try:
                return self._content_builder.build_page_content(
                    page_body_template=template.page_body_template,
                    fields=classification.fields,
                    transcript=transcription.text,
                    processed_at=metadata.captured_at,
                    device=metadata.device,
                    duration_seconds=metadata.duration_seconds,
                )
            except ContentBuildError as e:
                logger.warning(f"Content build error: {e}, using basic content")

        # Fall back to basic content builder
        summary = classification.fields.get("summary")
        return self._content_builder.build_basic_page_content(
            transcript=transcription.text,
            processed_at=metadata.captured_at,
            device=metadata.device,
            duration_seconds=metadata.duration_seconds,
            summary=summary,
        )

    async def _ensure_database_properties(
        self,
        template: TemplateConfig,
    ) -> None:
        """Ensure all required properties exist in the Notion database.

        Queries the database schema and auto-creates any missing properties
        defined by the template or needed as standard capture properties.
        Caches the schema to avoid repeated API calls.

        Args:
            template: Template configuration with field definitions.
        """
        if self._known_properties is None:
            try:
                db = await self._client.databases.retrieve(self._database_id)
                if isinstance(db, dict) and "properties" in db:
                    self._known_properties = set(db["properties"].keys())
                else:
                    self._known_properties = set()
                logger.debug(
                    f"Cached {len(self._known_properties)} existing Notion properties"
                )
            except Exception as e:
                logger.warning(f"Could not retrieve database schema: {e}")
                return

        missing: Dict[str, Any] = {}

        # Check template-specific fields
        for field_config in template.fields:
            prop_name = field_config.get_notion_property_name()
            if prop_name and prop_name not in self._known_properties:
                schema = self._field_type_to_schema(field_config)
                if schema:
                    missing[prop_name] = schema

        # Check standard properties present on all captures
        standard = {
            "Device": {"rich_text": {}},
            "Location": {"rich_text": {}},
            "Type": {"select": {}},
            "Tags": {"multi_select": {}},
            "Comments": {"rich_text": {}},
            "Related To": {"rich_text": {}},
        }
        for prop_name, schema in standard.items():
            if prop_name not in self._known_properties:
                missing[prop_name] = schema

        if not missing:
            return

        try:
            logger.info(
                f"Auto-creating {len(missing)} Notion properties: "
                f"{list(missing.keys())}"
            )
            await self._client.databases.update(
                database_id=self._database_id,
                properties=missing,
            )
            self._known_properties.update(missing.keys())
        except Exception as e:
            logger.warning(f"Could not auto-create database properties: {e}")
            self._known_properties = None  # Reset cache to retry next time

    def _field_type_to_schema(
        self, field_config: FieldConfig,
    ) -> Optional[Dict[str, Any]]:
        """Convert field configuration to Notion database property schema.

        Args:
            field_config: Field configuration from template.

        Returns:
            Notion property schema dict, or None for title fields.
        """
        ft = field_config.type
        if ft == FieldType.TITLE:
            return None  # Title property already exists
        elif ft == FieldType.RICH_TEXT:
            return {"rich_text": {}}
        elif ft == FieldType.DATE:
            return {"date": {}}
        elif ft == FieldType.SELECT:
            if field_config.options:
                return {
                    "select": {
                        "options": [{"name": o} for o in field_config.options]
                    }
                }
            return {"select": {}}
        elif ft == FieldType.MULTI_SELECT:
            if field_config.options:
                return {
                    "multi_select": {
                        "options": [{"name": o} for o in field_config.options]
                    }
                }
            return {"multi_select": {}}
        elif ft == FieldType.NUMBER:
            return {"number": {}}
        elif ft == FieldType.CHECKBOX:
            return {"checkbox": {}}
        return None

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

        Delegates to src.common.backoff.calculate_backoff.

        Args:
            attempt: Current retry attempt (0-indexed).

        Returns:
            Backoff delay in seconds.
        """
        return calculate_backoff(
            attempt=attempt,
            base_seconds=self._base_backoff,
            max_seconds=self._max_backoff,
            multiplier=2.0,
            jitter_factor=0.1,
        )

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
