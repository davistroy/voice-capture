"""Interface for classification services.

Defines the Protocol for classification service implementations,
enabling loose coupling and easier testing per work item 6.8.
"""

from typing import Optional, Protocol, TYPE_CHECKING

from src.models.classification import ClassificationResult

if TYPE_CHECKING:
    from src.classification.prompt_builder import TranscriptMetadata


class IClassificationService(Protocol):
    """Interface for classification services.

    Implementations should classify transcripts into template types
    and extract structured fields using LLM capabilities.

    Example implementations:
        - ClassificationService (Claude API)
        - MockClassificationService (for testing)

    Usage:
        def classify_transcript(
            service: IClassificationService,
            transcript: str
        ) -> ClassificationResult:
            return await service.classify(transcript)
    """

    async def classify(
        self,
        transcript: str,
        metadata: Optional["TranscriptMetadata"] = None,
    ) -> ClassificationResult:
        """Classify transcript into template type.

        Analyzes the transcript content and metadata to determine
        the most appropriate template type (e.g., task, journal, idea)
        and extracts structured fields for that template.

        Args:
            transcript: The transcript text to classify.
            metadata: Optional metadata about the transcript including
                     capture time, duration, and source device.

        Returns:
            ClassificationResult with template_name, confidence, fields,
            title, tags, and optional reasoning.

        Raises:
            ClassificationError: If classification fails after all retries.
        """
        ...
