"""
Template configuration dataclasses.

Defines the data structures for YAML-based template configuration per TDD 3.3.
Templates define triggers, fields, Notion mappings, and page body templates.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import os
import re


class FieldType(str, Enum):
    """
    Valid field types for template configuration.

    Maps to Notion property types per TDD 4.4.
    """
    TITLE = "title"
    DATE = "date"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    RICH_TEXT = "rich_text"
    NUMBER = "number"
    CHECKBOX = "checkbox"


@dataclass
class TriggersConfig:
    """
    Trigger configuration for template matching.

    Attributes:
        patterns: Explicit phrase patterns that indicate this template type.
        indicators: Semantic indicators for LLM to consider during classification.
    """
    patterns: List[str] = field(default_factory=list)
    indicators: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate trigger configuration."""
        if not isinstance(self.patterns, list):
            raise ValueError("triggers.patterns must be a list")
        if not isinstance(self.indicators, list):
            raise ValueError("triggers.indicators must be a list")
        if not all(isinstance(p, str) for p in self.patterns):
            raise ValueError("All patterns must be strings")
        if not all(isinstance(i, str) for i in self.indicators):
            raise ValueError("All indicators must be strings")

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TriggersConfig":
        """
        Create TriggersConfig from dictionary.

        Args:
            data: Dictionary with 'patterns' and 'indicators' keys.
                  If None, returns empty config.

        Returns:
            New TriggersConfig instance.
        """
        if data is None:
            return cls()
        return cls(
            patterns=data.get("patterns", []),
            indicators=data.get("indicators", []),
        )


@dataclass
class FieldConfig:
    """
    Field configuration for a template.

    Attributes:
        name: Field identifier (lowercase, no spaces).
        type: Field type (title, date, select, etc.).
        description: Human-readable description of what this field captures.
        extraction: Instruction for LLM on how to extract this field.
        required: Whether this field is required (default False).
        default: Default value if not extracted.
        options: Valid options for select/multi_select types.
        notion_property: Notion property name (defaults to name if not specified).
    """
    name: str
    type: FieldType
    description: str = ""
    extraction: str = ""
    required: bool = False
    default: Any = None
    options: List[str] = field(default_factory=list)
    notion_property: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate field configuration."""
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Field name must be a non-empty string")

        # Validate type
        if isinstance(self.type, str):
            try:
                self.type = FieldType(self.type)
            except ValueError:
                valid_types = [t.value for t in FieldType]
                raise ValueError(
                    f"Invalid field type '{self.type}'. "
                    f"Valid types: {valid_types}"
                )
        elif not isinstance(self.type, FieldType):
            raise ValueError("Field type must be a FieldType enum or valid string")

        # Validate options for select types
        if self.type in (FieldType.SELECT, FieldType.MULTI_SELECT):
            if not isinstance(self.options, list):
                raise ValueError(f"Field '{self.name}': options must be a list for select types")

        # notion_property left as None means this field is extraction-only
        # (available in page body template but not mapped to a Notion DB column)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldConfig":
        """
        Create FieldConfig from dictionary.

        Args:
            data: Dictionary with field configuration.

        Returns:
            New FieldConfig instance.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        if "name" not in data:
            raise ValueError("Field configuration requires 'name'")
        if "type" not in data:
            raise ValueError(f"Field '{data['name']}' requires 'type'")

        return cls(
            name=data["name"],
            type=data["type"],  # Will be converted in __post_init__
            description=data.get("description", ""),
            extraction=data.get("extraction", ""),
            required=data.get("required", False),
            default=data.get("default"),
            options=data.get("options", []),
            notion_property=data.get("notion_property"),
        )

    def get_notion_property_name(self) -> Optional[str]:
        """
        Get the Notion property name for this field.

        Returns:
            The notion_property if set, None if this field is extraction-only.
        """
        return self.notion_property


def interpolate_env_vars(value: str) -> str:
    """
    Interpolate environment variables in a string.

    Supports ${VAR} and ${VAR:default} syntax.

    Args:
        value: String potentially containing ${VAR} references.

    Returns:
        String with environment variables resolved.
    """
    if not isinstance(value, str):
        return value

    # Pattern matches ${VAR} or ${VAR:default}
    pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

    def replace(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)
        env_value = os.environ.get(var_name)
        if env_value is not None:
            return env_value
        if default is not None:
            return default
        return match.group(0)  # Return original if not found and no default

    return re.sub(pattern, replace, value)


@dataclass
class TemplateConfig:
    """
    Complete template configuration.

    Loaded from YAML files in config/templates/.

    Attributes:
        name: Internal identifier (lowercase, no spaces).
        display_name: Human-readable name.
        description: Purpose of this template.
        enabled: Whether this template is active (default True).
        triggers: Trigger patterns and indicators.
        fields: List of field configurations.
        notion_database_id: Notion database ID (supports env var interpolation).
        page_body_template: Jinja2 template string for page content.
    """
    name: str
    display_name: str
    description: str = ""
    enabled: bool = True
    triggers: TriggersConfig = field(default_factory=TriggersConfig)
    fields: List[FieldConfig] = field(default_factory=list)
    notion_database_id: str = ""
    page_body_template: str = ""

    def __post_init__(self) -> None:
        """Validate template configuration."""
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Template name must be a non-empty string")
        if not isinstance(self.display_name, str) or not self.display_name:
            raise ValueError("Template display_name must be a non-empty string")
        if not isinstance(self.enabled, bool):
            raise ValueError("Template enabled must be a boolean")
        if not isinstance(self.fields, list):
            raise ValueError("Template fields must be a list")

        # Interpolate environment variables in notion_database_id
        if self.notion_database_id:
            self.notion_database_id = interpolate_env_vars(self.notion_database_id)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateConfig":
        """
        Create TemplateConfig from dictionary (parsed YAML).

        Args:
            data: Dictionary with template configuration.

        Returns:
            New TemplateConfig instance.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        # Required fields
        if "name" not in data:
            raise ValueError("Template configuration requires 'name'")
        if "display_name" not in data:
            raise ValueError(f"Template '{data['name']}' requires 'display_name'")

        # Parse fields
        fields_data = data.get("fields", [])
        fields = [FieldConfig.from_dict(f) for f in fields_data]

        # Parse triggers
        triggers = TriggersConfig.from_dict(data.get("triggers"))

        # Extract notion database_id from nested 'notion' dict or top-level
        notion_config = data.get("notion", {})
        database_id = notion_config.get("database_id", "") if isinstance(notion_config, dict) else ""

        return cls(
            name=data["name"],
            display_name=data["display_name"],
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            triggers=triggers,
            fields=fields,
            notion_database_id=database_id,
            page_body_template=data.get("page_body_template", ""),
        )

    def get_required_fields(self) -> List[FieldConfig]:
        """
        Get all required fields for this template.

        Returns:
            List of FieldConfig where required=True.
        """
        return [f for f in self.fields if f.required]

    def get_optional_fields(self) -> List[FieldConfig]:
        """
        Get all optional fields for this template.

        Returns:
            List of FieldConfig where required=False.
        """
        return [f for f in self.fields if not f.required]

    def get_field(self, name: str) -> Optional[FieldConfig]:
        """
        Get a specific field by name.

        Args:
            name: Field name to look up.

        Returns:
            FieldConfig if found, None otherwise.
        """
        for field in self.fields:
            if field.name == name:
                return field
        return None

    def get_field_names(self) -> List[str]:
        """
        Get all field names for this template.

        Returns:
            List of field names.
        """
        return [f.name for f in self.fields]

    def has_field(self, name: str) -> bool:
        """
        Check if template has a field with the given name.

        Args:
            name: Field name to check.

        Returns:
            True if field exists.
        """
        return self.get_field(name) is not None

    def validate_extracted_fields(
        self,
        extracted: Dict[str, Any],
        apply_defaults: bool = True,
    ) -> Dict[str, Any]:
        """
        Validate extracted fields against template definition.

        Args:
            extracted: Dictionary of extracted field values.
            apply_defaults: Whether to apply defaults for missing optional fields.

        Returns:
            Validated fields dictionary with defaults applied.

        Raises:
            ValueError: If required fields are missing.
        """
        validated = {}
        missing_required = []

        for field_config in self.fields:
            if field_config.name in extracted:
                validated[field_config.name] = extracted[field_config.name]
            elif field_config.required:
                missing_required.append(field_config.name)
            elif apply_defaults and field_config.default is not None:
                validated[field_config.name] = field_config.default

        if missing_required:
            raise ValueError(
                f"Template '{self.name}' missing required fields: {missing_required}"
            )

        return validated

    def build_prompt_section(self) -> str:
        """
        Build the classification prompt section for this template.

        Used by TemplateLoader.build_classification_prompt_context().

        Returns:
            Formatted string describing this template for the LLM.
        """
        lines = [
            f"### {self.display_name}",
            f"**Purpose:** {self.description}",
        ]

        if self.triggers.patterns:
            lines.append(f"**Trigger patterns:** {self.triggers.patterns}")

        if self.triggers.indicators:
            lines.append(f"**Semantic indicators:** {self.triggers.indicators}")

        lines.append("")
        lines.append("**Fields to extract:**")

        for field_config in self.fields:
            line = f"- {field_config.name} ({field_config.type.value}): {field_config.description}"
            if field_config.extraction:
                line += f"\n  Extraction guidance: {field_config.extraction}"
            if field_config.options:
                line += f"\n  Options: {field_config.options}"
            if field_config.required:
                line += " [REQUIRED]"
            lines.append(line)

        return "\n".join(lines)
