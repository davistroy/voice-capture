"""
Classification module for voice capture pipeline.

This module provides:
- TemplateConfig: Dataclass for template configuration from YAML
- FieldConfig: Dataclass for template field definitions
- TriggersConfig: Dataclass for template trigger patterns
- TemplateLoader: Loads and validates YAML template configurations
"""

from src.classification.template_config import (
    TemplateConfig,
    FieldConfig,
    TriggersConfig,
    FieldType,
)
from src.classification.template_loader import TemplateLoader

__all__ = [
    "TemplateConfig",
    "FieldConfig",
    "TriggersConfig",
    "FieldType",
    "TemplateLoader",
]
