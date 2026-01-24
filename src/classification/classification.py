"""
Classification service for voice capture pipeline.

Handles transcript classification and field extraction using Claude API
per TDD Section 4.3.

Preferred instantiation pattern:
    # Using factory method (recommended)
    from src.config.settings import get_settings
    settings = get_settings()
    service = ClassificationService.from_settings(settings)

    # Direct instantiation (for testing or custom configuration)
    from anthropic import Anthropic
    client = Anthropic(api_key="...")
    loader = TemplateLoader.from_directory(Path("config/templates"))
    service = ClassificationService(anthropic_client=client, template_loader=loader)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import yaml

from src.classification.template_loader import TemplateLoader
from src.common.backoff import calculate_backoff
from src.classification.prompt_builder import PromptBuilder, TranscriptMetadata, build_corrective_prompt
from src.classification.response_parser import (
    ResponseParser,
    ParseError,
    ValidationError,
    create_fallback_result,
)
from src.models.classification import ClassificationResult

if TYPE_CHECKING:
    from src.config.settings import Settings


logger = logging.getLogger(__name__)


@dataclass
class ClassificationConfig:
    """
    Configuration for the classification service.

    Loaded from config/classification.yaml.
    """
    confidence_threshold: float = 0.7
    fallback_template: str = "general"
    template_priority: List[str] = field(default_factory=list)
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 2048
    max_retries: int = 3
    base_backoff_seconds: float = 5.0
    max_backoff_seconds: float = 300.0
    backoff_multiplier: float = 2.0
    system_context: str = ""

    @classmethod
    def from_file(cls, config_path: Path) -> "ClassificationConfig":
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to classification.yaml.

        Returns:
            ClassificationConfig with loaded values.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            ValueError: If config file is invalid.
        """
        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return cls()

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return cls()

        return cls(
            confidence_threshold=data.get("confidence_threshold", 0.7),
            fallback_template=data.get("fallback_template", "general"),
            template_priority=data.get("template_priority", []),
            model=data.get("model", "claude-sonnet-4-20250514"),
            max_tokens=data.get("max_tokens", 2048),
            max_retries=data.get("max_retries", 3),
            base_backoff_seconds=data.get("base_backoff_seconds", 5.0),
            max_backoff_seconds=data.get("max_backoff_seconds", 300.0),
            backoff_multiplier=data.get("backoff_multiplier", 2.0),
            system_context=data.get("system_context", ""),
        )

    def get_backoff(self, retry_count: int) -> float:
        """
        Calculate exponential backoff with jitter.

        Delegates to src.common.backoff.calculate_backoff.

        Args:
            retry_count: Current retry attempt (0-indexed).

        Returns:
            Backoff duration in seconds.
        """
        return calculate_backoff(
            attempt=retry_count,
            base_seconds=self.base_backoff_seconds,
            max_seconds=self.max_backoff_seconds,
            multiplier=self.backoff_multiplier,
            jitter_factor=0.1,  # 10% jitter, matching original behavior
        )


class ClassificationError(Exception):
    """Raised when classification fails after all retries."""

    def __init__(self, message: str, last_error: Optional[Exception] = None):
        self.message = message
        self.last_error = last_error
        super().__init__(message)


class ClassificationService:
    """
    Handles transcript classification and field extraction.

    Uses Claude API to classify transcripts into templates and
    extract structured fields. Includes retry logic with exponential
    backoff and fallback handling.

    Example usage:
        from anthropic import Anthropic

        client = Anthropic(api_key="sk-...")
        loader = TemplateLoader.from_directory(Path("config/templates"))

        service = ClassificationService(
            anthropic_client=client,
            template_loader=loader,
        )

        result = await service.classify(
            transcript="I need to review the quarterly report by Friday",
            metadata=TranscriptMetadata(
                captured_at=datetime.now(),
                duration_seconds=15.5,
                device="watch",
            ),
        )
    """

    def __init__(
        self,
        anthropic_client: Any,  # Anthropic client
        template_loader: TemplateLoader,
        config: Optional[ClassificationConfig] = None,
    ):
        """
        Initialize the classification service.

        Args:
            anthropic_client: Initialized Anthropic API client.
            template_loader: Template loader with templates loaded.
            config: Optional configuration (loads from file if None).
        """
        self.client = anthropic_client
        self.template_loader = template_loader
        self.config = config or ClassificationConfig()

        # Initialize prompt builder and response parser
        self.prompt_builder = PromptBuilder(
            template_loader=template_loader,
            system_context=self.config.system_context,
            confidence_threshold=self.config.confidence_threshold,
        )

        self.response_parser = ResponseParser(
            template_loader=template_loader,
            confidence_threshold=self.config.confidence_threshold,
            fallback_template=self.config.fallback_template,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> ClassificationService:
        """
        Create a ClassificationService from application settings.

        This is the preferred way to instantiate the service in production code.
        It extracts all necessary configuration from the Settings object,
        creates the Anthropic client, and loads templates.

        Args:
            settings: Application settings containing classification configuration
                and API keys.

        Returns:
            Configured ClassificationService instance.

        Example:
            from src.config.settings import get_settings
            settings = get_settings()
            service = ClassificationService.from_settings(settings)
        """
        from anthropic import Anthropic

        # Create Anthropic client
        anthropic_client = Anthropic(api_key=settings.anthropic_api_key)

        # Load templates from configured path
        template_loader = TemplateLoader.from_directory(settings.paths.templates)

        # Build classification config from settings
        config = ClassificationConfig(
            model=settings.classification.model,
            confidence_threshold=settings.classification.confidence_threshold,
            max_tokens=settings.classification.max_tokens,
            max_retries=settings.pipeline.max_retries,
            base_backoff_seconds=settings.pipeline.base_backoff_seconds,
            max_backoff_seconds=settings.pipeline.max_backoff_seconds,
        )

        return cls(
            anthropic_client=anthropic_client,
            template_loader=template_loader,
            config=config,
        )

    async def classify(
        self,
        transcript: str,
        metadata: Optional[TranscriptMetadata] = None,
    ) -> ClassificationResult:
        """
        Classify a transcript and extract template fields.

        Args:
            transcript: The transcript text to classify.
            metadata: Optional metadata about the transcript.

        Returns:
            ClassificationResult with template, fields, title, and tags.

        Raises:
            ClassificationError: If classification fails after all retries.
        """
        if not transcript or not transcript.strip():
            logger.warning("Empty transcript provided, using fallback")
            return create_fallback_result("", "Empty transcript")

        # Build the classification prompt
        prompt = self.prompt_builder.build_classification_prompt(
            transcript=transcript,
            metadata=metadata,
        )

        # Call Claude API with retry logic
        last_error: Optional[Exception] = None
        response_text: Optional[str] = None

        for attempt in range(self.config.max_retries):
            try:
                response_text = await self._call_claude_api(prompt)
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Classification API call failed (attempt {attempt + 1}/"
                    f"{self.config.max_retries}): {e}"
                )

                if attempt < self.config.max_retries - 1:
                    backoff = self.config.get_backoff(attempt)
                    logger.info(f"Retrying in {backoff:.1f} seconds...")
                    await asyncio.sleep(backoff)

        if response_text is None:
            logger.error(f"Classification failed after {self.config.max_retries} retries")
            return create_fallback_result(transcript, f"API call failed: {last_error}")

        # Parse the response with retry for JSON errors
        try:
            return self._parse_with_retry(response_text, transcript)
        except Exception as e:
            logger.error(f"Failed to parse classification response: {e}")
            return create_fallback_result(transcript, f"Parse error: {e}")

    def _parse_with_retry(
        self,
        response_text: str,
        transcript: str,
    ) -> ClassificationResult:
        """
        Parse response with one retry using corrective prompt.

        Args:
            response_text: Initial response from Claude.
            transcript: Original transcript (for fallback).

        Returns:
            Parsed ClassificationResult.
        """
        try:
            return self.response_parser.parse(response_text)
        except ParseError as e:
            logger.warning(f"JSON parse error, attempting corrective retry: {e}")

            # Try once more with a corrective prompt
            try:
                corrective_prompt = build_corrective_prompt(
                    original_response=response_text,
                    error_message=str(e),
                )

                # Synchronous retry (we're already in an async context)
                loop = asyncio.get_event_loop()
                retry_response = loop.run_until_complete(
                    self._call_claude_api(corrective_prompt)
                )

                return self.response_parser.parse(retry_response)
            except Exception as retry_error:
                logger.error(f"Corrective retry also failed: {retry_error}")
                raise e  # Re-raise original error
        except ValidationError as e:
            logger.error(f"Validation error in classification response: {e}")
            raise

    async def _call_claude_api(self, prompt: str) -> str:
        """
        Call Claude API with the classification prompt.

        Args:
            prompt: Full prompt to send.

        Returns:
            Response text from Claude.

        Raises:
            Exception: If API call fails.
        """
        # Make the API call
        create_func = self.client.messages.create
        response = create_func(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        # Handle coroutine response (async client)
        if asyncio.iscoroutine(response):
            response = await response

        # Extract text from response
        if response.content and len(response.content) > 0:
            return response.content[0].text

        raise ClassificationError("Empty response from Claude API")

    def classify_sync(
        self,
        transcript: str,
        metadata: Optional[TranscriptMetadata] = None,
    ) -> ClassificationResult:
        """
        Synchronous wrapper for classify().

        For use in non-async contexts.

        Args:
            transcript: The transcript text to classify.
            metadata: Optional metadata about the transcript.

        Returns:
            ClassificationResult.
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.classify(transcript, metadata))
        finally:
            loop.close()


def load_classification_config(config_path: Optional[Path] = None) -> ClassificationConfig:
    """
    Load classification configuration from file.

    Args:
        config_path: Path to config file. Defaults to config/classification.yaml.

    Returns:
        Loaded ClassificationConfig.
    """
    if config_path is None:
        config_path = Path("config/classification.yaml")

    return ClassificationConfig.from_file(config_path)
