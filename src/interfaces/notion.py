"""Interface for Notion integration services.

Defines the Protocol for Notion service implementations,
enabling loose coupling and easier testing per work item 6.8.
"""

from typing import Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.transcription import TranscriptionResult
    from src.models.classification import ClassificationResult
    from src.notion.client import CaptureMetadata, NotionPage
    from src.classification.template_config import TemplateConfig


class INotionService(Protocol):
    """Interface for Notion integration.

    Implementations should handle creating and managing pages
    in a Notion database for voice capture storage.

    Example implementations:
        - NotionService (Notion API client)
        - MockNotionService (for testing)

    Usage:
        async def save_capture(
            service: INotionService,
            transcription: TranscriptionResult,
            metadata: CaptureMetadata
        ) -> NotionPage:
            return await service.create_capture_page(
                transcription=transcription,
                metadata=metadata
            )
    """

    async def create_capture_page(
        self,
        transcription: "TranscriptionResult",
        metadata: "CaptureMetadata",
        title: Optional[str] = None,
        classification: Optional["ClassificationResult"] = None,
        template: Optional["TemplateConfig"] = None,
    ) -> "NotionPage":
        """Create a Notion page for a capture.

        Creates a new page in the Voice Captures database with the
        transcription content and metadata. When classification and
        template are provided, creates template-specific pages with
        extracted fields mapped to Notion properties.

        Args:
            transcription: The transcription result with text and duration.
            metadata: Capture metadata with timestamp, device, and duration.
            title: Optional custom title. If not provided, generated from
                  classification title or first sentence of transcript.
            classification: Optional classification result with template
                          and extracted fields (Phase 2+).
            template: Optional template configuration for property mapping
                     (Phase 2+).

        Returns:
            NotionPage with id and url on success.

        Raises:
            NotionError: On permanent failure after all retries.
            NotionRateLimitError: On rate limit with retry_after hint.
        """
        ...

    async def close(self) -> None:
        """Close the underlying HTTP client.

        Should be called when the service is no longer needed
        to release resources.
        """
        ...
