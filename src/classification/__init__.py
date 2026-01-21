"""
Classification module for voice capture pipeline.

This module provides:
- TemplateConfig: Dataclass for template configuration from YAML
- FieldConfig: Dataclass for template field definitions
- TriggersConfig: Dataclass for template trigger patterns
- TemplateLoader: Loads and validates YAML template configurations
- ClassificationService: LLM-based classification using Claude
- ClassificationConfig: Configuration for classification behavior
- PromptBuilder: Builds classification prompts from templates
- TranscriptMetadata: Metadata about transcripts being classified
- ResponseParser: Parses and validates LLM responses
"""

from src.classification.template_config import (
    TemplateConfig,
    FieldConfig,
    TriggersConfig,
    FieldType,
)
from src.classification.template_loader import TemplateLoader
from src.classification.classification import (
    ClassificationService,
    ClassificationConfig,
    ClassificationError,
    load_classification_config,
)
from src.classification.prompt_builder import (
    PromptBuilder,
    TranscriptMetadata,
    build_corrective_prompt,
)
from src.classification.response_parser import (
    ResponseParser,
    ParseError,
    ValidationError,
    create_fallback_result,
)

__all__ = [
    # Template configuration
    "TemplateConfig",
    "FieldConfig",
    "TriggersConfig",
    "FieldType",
    "TemplateLoader",
    # Classification service
    "ClassificationService",
    "ClassificationConfig",
    "ClassificationError",
    "load_classification_config",
    # Prompt building
    "PromptBuilder",
    "TranscriptMetadata",
    "build_corrective_prompt",
    # Response parsing
    "ResponseParser",
    "ParseError",
    "ValidationError",
    "create_fallback_result",
]
