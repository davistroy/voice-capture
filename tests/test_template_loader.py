"""
Unit tests for template configuration and loader.

Tests the TemplateConfig, FieldConfig, TriggersConfig dataclasses
and the TemplateLoader class for loading YAML templates.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, Any

import pytest
import yaml

from src.classification.template_config import (
    TemplateConfig,
    FieldConfig,
    TriggersConfig,
    FieldType,
    interpolate_env_vars,
)
from src.classification.template_loader import (
    TemplateLoader,
    TemplateLoadError,
    TemplateValidationError,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_field_data() -> Dict[str, Any]:
    """Sample field configuration data."""
    return {
        "name": "title",
        "type": "title",
        "description": "Page title",
        "extraction": "Extract the core concept",
        "required": True,
        "notion_property": "Task Title",
    }


@pytest.fixture
def sample_template_data() -> Dict[str, Any]:
    """Sample template configuration data."""
    return {
        "name": "task",
        "display_name": "Task",
        "description": "Action items and to-dos",
        "enabled": True,
        "triggers": {
            "patterns": ["I need to", "remind me to", "task:"],
            "indicators": ["imperative statements", "action commitments"],
        },
        "fields": [
            {
                "name": "title",
                "type": "title",
                "description": "Task title",
                "extraction": "Extract the core action",
                "required": True,
            },
            {
                "name": "priority",
                "type": "select",
                "description": "Priority level",
                "extraction": "Infer from urgency",
                "options": ["High", "Medium", "Low"],
                "default": "Medium",
            },
            {
                "name": "tags",
                "type": "multi_select",
                "description": "Topic tags",
                "extraction": "Generate 2-5 tags",
                "options": [],
            },
        ],
        "notion": {
            "database_id": "${NOTION_VOICE_CAPTURES_DB_ID}",
        },
        "page_body_template": "## Summary\n{{ summary }}\n\n## Transcript\n{{ transcript }}",
    }


@pytest.fixture
def temp_templates_dir(tmp_path: Path) -> Path:
    """Create a temporary templates directory."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    return templates_dir


@pytest.fixture
def loader_with_templates(temp_templates_dir: Path, sample_template_data: Dict[str, Any]) -> TemplateLoader:
    """Create a loader with sample templates."""
    # Write task template
    task_file = temp_templates_dir / "task.yaml"
    with open(task_file, "w") as f:
        yaml.dump(sample_template_data, f)

    # Write general template
    general_data = {
        "name": "general",
        "display_name": "General",
        "description": "Fallback for unclassified content",
        "enabled": True,
        "triggers": {"patterns": [], "indicators": []},
        "fields": [
            {
                "name": "title",
                "type": "title",
                "description": "Page title",
                "required": True,
            },
            {
                "name": "summary",
                "type": "rich_text",
                "description": "Summary of content",
            },
        ],
        "notion": {"database_id": "test-db-id"},
        "page_body_template": "{{ summary }}\n{{ transcript }}",
    }
    general_file = temp_templates_dir / "general.yaml"
    with open(general_file, "w") as f:
        yaml.dump(general_data, f)

    loader = TemplateLoader(temp_templates_dir)
    loader.load_all()
    return loader


# =============================================================================
# FieldType Tests
# =============================================================================


class TestFieldType:
    """Tests for FieldType enum."""

    def test_all_types_defined(self):
        """Verify all expected field types exist."""
        expected = ["title", "date", "select", "multi_select", "rich_text", "number", "checkbox"]
        actual = [t.value for t in FieldType]
        assert set(expected) == set(actual)

    def test_string_values(self):
        """Field types should have string values."""
        assert FieldType.TITLE.value == "title"
        assert FieldType.DATE.value == "date"
        assert FieldType.SELECT.value == "select"
        assert FieldType.MULTI_SELECT.value == "multi_select"
        assert FieldType.RICH_TEXT.value == "rich_text"
        assert FieldType.NUMBER.value == "number"
        assert FieldType.CHECKBOX.value == "checkbox"


# =============================================================================
# TriggersConfig Tests
# =============================================================================


class TestTriggersConfig:
    """Tests for TriggersConfig dataclass."""

    def test_create_with_defaults(self):
        """Create triggers with empty defaults."""
        triggers = TriggersConfig()
        assert triggers.patterns == []
        assert triggers.indicators == []

    def test_create_with_values(self):
        """Create triggers with patterns and indicators."""
        triggers = TriggersConfig(
            patterns=["I need to", "remind me"],
            indicators=["imperative statements"],
        )
        assert triggers.patterns == ["I need to", "remind me"]
        assert triggers.indicators == ["imperative statements"]

    def test_from_dict(self):
        """Create from dictionary."""
        data = {
            "patterns": ["task:"],
            "indicators": ["action items"],
        }
        triggers = TriggersConfig.from_dict(data)
        assert triggers.patterns == ["task:"]
        assert triggers.indicators == ["action items"]

    def test_from_dict_none(self):
        """Handle None input."""
        triggers = TriggersConfig.from_dict(None)
        assert triggers.patterns == []
        assert triggers.indicators == []

    def test_from_dict_empty(self):
        """Handle empty dictionary."""
        triggers = TriggersConfig.from_dict({})
        assert triggers.patterns == []
        assert triggers.indicators == []

    def test_validation_patterns_must_be_list(self):
        """Patterns must be a list."""
        with pytest.raises(ValueError, match="patterns must be a list"):
            TriggersConfig(patterns="not a list")

    def test_validation_indicators_must_be_list(self):
        """Indicators must be a list."""
        with pytest.raises(ValueError, match="indicators must be a list"):
            TriggersConfig(indicators="not a list")

    def test_validation_patterns_must_be_strings(self):
        """Pattern items must be strings."""
        with pytest.raises(ValueError, match="All patterns must be strings"):
            TriggersConfig(patterns=[123, 456])


# =============================================================================
# FieldConfig Tests
# =============================================================================


class TestFieldConfig:
    """Tests for FieldConfig dataclass."""

    def test_create_minimal(self):
        """Create field with minimal required values."""
        field = FieldConfig(name="title", type=FieldType.TITLE)
        assert field.name == "title"
        assert field.type == FieldType.TITLE
        assert field.description == ""
        assert field.required is False
        assert field.default is None
        assert field.options == []
        assert field.notion_property == "title"  # Defaults to name

    def test_create_full(self, sample_field_data: Dict[str, Any]):
        """Create field with all values."""
        field = FieldConfig.from_dict(sample_field_data)
        assert field.name == "title"
        assert field.type == FieldType.TITLE
        assert field.description == "Page title"
        assert field.extraction == "Extract the core concept"
        assert field.required is True
        assert field.notion_property == "Task Title"

    def test_type_conversion_from_string(self):
        """String type should be converted to enum."""
        field = FieldConfig(name="test", type="date")
        assert field.type == FieldType.DATE

    def test_invalid_type_string(self):
        """Invalid type string should raise."""
        with pytest.raises(ValueError, match="Invalid field type"):
            FieldConfig(name="test", type="invalid_type")

    def test_validation_name_required(self):
        """Name must be non-empty."""
        with pytest.raises(ValueError, match="name must be a non-empty string"):
            FieldConfig(name="", type=FieldType.TITLE)

    def test_validation_select_options(self):
        """Select fields should have options."""
        # This creates the field but validation happens at template level
        field = FieldConfig(
            name="status",
            type=FieldType.SELECT,
            options=["Open", "Closed"],
        )
        assert field.options == ["Open", "Closed"]

    def test_notion_property_defaults_to_name(self):
        """notion_property should default to field name."""
        field = FieldConfig(name="my_field", type=FieldType.RICH_TEXT)
        assert field.get_notion_property_name() == "my_field"

    def test_notion_property_override(self):
        """notion_property can be overridden."""
        field = FieldConfig(
            name="my_field",
            type=FieldType.RICH_TEXT,
            notion_property="My Custom Field",
        )
        assert field.get_notion_property_name() == "My Custom Field"

    def test_from_dict_missing_name(self):
        """from_dict should require name."""
        with pytest.raises(ValueError, match="requires 'name'"):
            FieldConfig.from_dict({"type": "title"})

    def test_from_dict_missing_type(self):
        """from_dict should require type."""
        with pytest.raises(ValueError, match="requires 'type'"):
            FieldConfig.from_dict({"name": "test"})


# =============================================================================
# Environment Variable Interpolation Tests
# =============================================================================


class TestEnvVarInterpolation:
    """Tests for environment variable interpolation."""

    def test_interpolate_simple(self, monkeypatch):
        """Simple ${VAR} interpolation."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = interpolate_env_vars("prefix_${TEST_VAR}_suffix")
        assert result == "prefix_test_value_suffix"

    def test_interpolate_with_default(self, monkeypatch):
        """${VAR:default} syntax with default."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = interpolate_env_vars("${MISSING_VAR:default_value}")
        assert result == "default_value"

    def test_interpolate_default_not_used(self, monkeypatch):
        """Default not used when var exists."""
        monkeypatch.setenv("EXISTING_VAR", "real_value")
        result = interpolate_env_vars("${EXISTING_VAR:default_value}")
        assert result == "real_value"

    def test_interpolate_empty_default(self, monkeypatch):
        """Empty default is valid."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = interpolate_env_vars("prefix${MISSING_VAR:}suffix")
        assert result == "prefixsuffix"

    def test_interpolate_missing_no_default(self, monkeypatch):
        """Missing var without default returns original."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = interpolate_env_vars("${MISSING_VAR}")
        assert result == "${MISSING_VAR}"

    def test_interpolate_non_string(self):
        """Non-string input returned unchanged."""
        assert interpolate_env_vars(123) == 123
        assert interpolate_env_vars(None) is None

    def test_interpolate_multiple_vars(self, monkeypatch):
        """Multiple variables in one string."""
        monkeypatch.setenv("VAR1", "one")
        monkeypatch.setenv("VAR2", "two")
        result = interpolate_env_vars("${VAR1}-${VAR2}")
        assert result == "one-two"


# =============================================================================
# TemplateConfig Tests
# =============================================================================


class TestTemplateConfig:
    """Tests for TemplateConfig dataclass."""

    def test_create_minimal(self):
        """Create template with minimal required values."""
        template = TemplateConfig(
            name="test",
            display_name="Test Template",
            fields=[FieldConfig(name="title", type=FieldType.TITLE)],
        )
        assert template.name == "test"
        assert template.display_name == "Test Template"
        assert template.enabled is True
        assert len(template.fields) == 1

    def test_create_from_dict(self, sample_template_data: Dict[str, Any]):
        """Create template from dictionary."""
        template = TemplateConfig.from_dict(sample_template_data)
        assert template.name == "task"
        assert template.display_name == "Task"
        assert template.description == "Action items and to-dos"
        assert template.enabled is True
        assert len(template.fields) == 3
        assert len(template.triggers.patterns) == 3
        assert len(template.triggers.indicators) == 2

    def test_env_var_interpolation_in_database_id(self, sample_template_data: Dict[str, Any], monkeypatch):
        """Database ID should interpolate env vars."""
        monkeypatch.setenv("NOTION_VOICE_CAPTURES_DB_ID", "real-db-id-123")
        template = TemplateConfig.from_dict(sample_template_data)
        assert template.notion_database_id == "real-db-id-123"

    def test_get_required_fields(self, sample_template_data: Dict[str, Any]):
        """Get required fields only."""
        template = TemplateConfig.from_dict(sample_template_data)
        required = template.get_required_fields()
        assert len(required) == 1
        assert required[0].name == "title"

    def test_get_optional_fields(self, sample_template_data: Dict[str, Any]):
        """Get optional fields only."""
        template = TemplateConfig.from_dict(sample_template_data)
        optional = template.get_optional_fields()
        assert len(optional) == 2
        assert "priority" in [f.name for f in optional]
        assert "tags" in [f.name for f in optional]

    def test_get_field(self, sample_template_data: Dict[str, Any]):
        """Get field by name."""
        template = TemplateConfig.from_dict(sample_template_data)
        field = template.get_field("priority")
        assert field is not None
        assert field.type == FieldType.SELECT

    def test_get_field_not_found(self, sample_template_data: Dict[str, Any]):
        """Get field returns None if not found."""
        template = TemplateConfig.from_dict(sample_template_data)
        assert template.get_field("nonexistent") is None

    def test_has_field(self, sample_template_data: Dict[str, Any]):
        """Check field existence."""
        template = TemplateConfig.from_dict(sample_template_data)
        assert template.has_field("title") is True
        assert template.has_field("nonexistent") is False

    def test_get_field_names(self, sample_template_data: Dict[str, Any]):
        """Get all field names."""
        template = TemplateConfig.from_dict(sample_template_data)
        names = template.get_field_names()
        assert names == ["title", "priority", "tags"]

    def test_validate_extracted_fields_valid(self, sample_template_data: Dict[str, Any]):
        """Validate valid extracted fields."""
        template = TemplateConfig.from_dict(sample_template_data)
        extracted = {"title": "My Task", "priority": "High"}
        validated = template.validate_extracted_fields(extracted)
        assert validated["title"] == "My Task"
        assert validated["priority"] == "High"

    def test_validate_extracted_fields_missing_required(self, sample_template_data: Dict[str, Any]):
        """Validation fails if required field missing."""
        template = TemplateConfig.from_dict(sample_template_data)
        with pytest.raises(ValueError, match="missing required fields"):
            template.validate_extracted_fields({"priority": "High"})

    def test_validate_extracted_fields_applies_defaults(self, sample_template_data: Dict[str, Any]):
        """Defaults applied to missing optional fields."""
        template = TemplateConfig.from_dict(sample_template_data)
        extracted = {"title": "My Task"}
        validated = template.validate_extracted_fields(extracted)
        assert validated.get("priority") == "Medium"

    def test_build_prompt_section(self, sample_template_data: Dict[str, Any]):
        """Build prompt section for classification."""
        template = TemplateConfig.from_dict(sample_template_data)
        section = template.build_prompt_section()
        assert "### Task" in section
        assert "Action items and to-dos" in section
        assert "I need to" in section
        assert "title" in section
        assert "[REQUIRED]" in section

    def test_validation_name_required(self):
        """Name must be non-empty."""
        with pytest.raises(ValueError, match="name must be a non-empty string"):
            TemplateConfig(name="", display_name="Test")

    def test_validation_display_name_required(self):
        """Display name must be non-empty."""
        with pytest.raises(ValueError, match="display_name must be a non-empty string"):
            TemplateConfig(name="test", display_name="")


# =============================================================================
# TemplateLoader Tests
# =============================================================================


class TestTemplateLoader:
    """Tests for TemplateLoader class."""

    def test_load_all_success(self, loader_with_templates: TemplateLoader):
        """Successfully load all templates."""
        assert len(loader_with_templates) == 2
        assert "task" in loader_with_templates
        assert "general" in loader_with_templates

    def test_load_all_directory_not_found(self, tmp_path: Path):
        """Raise error if directory doesn't exist."""
        loader = TemplateLoader(tmp_path / "nonexistent")
        with pytest.raises(FileNotFoundError):
            loader.load_all()

    def test_load_all_skips_underscore_files(self, temp_templates_dir: Path, sample_template_data: Dict[str, Any]):
        """Files starting with _ should be skipped."""
        # Write a template example file
        example_file = temp_templates_dir / "_template.yaml"
        with open(example_file, "w") as f:
            yaml.dump(sample_template_data, f)

        # Write a real template
        real_file = temp_templates_dir / "task.yaml"
        with open(real_file, "w") as f:
            yaml.dump(sample_template_data, f)

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()

        assert count == 1
        assert "task" in loader
        # _template.yaml content would have name "task" but is skipped

    def test_get_template(self, loader_with_templates: TemplateLoader):
        """Get specific template by name."""
        task = loader_with_templates.get_template("task")
        assert task is not None
        assert task.name == "task"
        assert task.display_name == "Task"

    def test_get_template_not_found(self, loader_with_templates: TemplateLoader):
        """Returns None if template not found."""
        assert loader_with_templates.get_template("nonexistent") is None

    def test_get_enabled_templates(self, temp_templates_dir: Path, sample_template_data: Dict[str, Any]):
        """Get only enabled templates."""
        # Write enabled template
        enabled_data = sample_template_data.copy()
        enabled_data["name"] = "enabled"
        enabled_data["enabled"] = True
        with open(temp_templates_dir / "enabled.yaml", "w") as f:
            yaml.dump(enabled_data, f)

        # Write disabled template
        disabled_data = sample_template_data.copy()
        disabled_data["name"] = "disabled"
        disabled_data["enabled"] = False
        with open(temp_templates_dir / "disabled.yaml", "w") as f:
            yaml.dump(disabled_data, f)

        loader = TemplateLoader(temp_templates_dir)
        loader.load_all()

        enabled = loader.get_enabled_templates()
        assert len(enabled) == 1
        assert enabled[0].name == "enabled"

    def test_get_disabled_templates(self, temp_templates_dir: Path, sample_template_data: Dict[str, Any]):
        """Get only disabled templates."""
        disabled_data = sample_template_data.copy()
        disabled_data["name"] = "disabled"
        disabled_data["enabled"] = False
        with open(temp_templates_dir / "disabled.yaml", "w") as f:
            yaml.dump(disabled_data, f)

        loader = TemplateLoader(temp_templates_dir)
        loader.load_all()

        disabled = loader.get_disabled_templates()
        assert len(disabled) == 1
        assert disabled[0].name == "disabled"

    def test_has_template(self, loader_with_templates: TemplateLoader):
        """Check if template exists."""
        assert loader_with_templates.has_template("task") is True
        assert loader_with_templates.has_template("nonexistent") is False

    def test_get_template_names(self, loader_with_templates: TemplateLoader):
        """Get all template names."""
        names = loader_with_templates.get_template_names()
        assert set(names) == {"task", "general"}

    def test_build_classification_prompt_context(self, loader_with_templates: TemplateLoader):
        """Build prompt context for classification."""
        context = loader_with_templates.build_classification_prompt_context()
        assert "### Task" in context
        assert "### General" in context
        assert "Action items" in context

    def test_build_classification_prompt_context_empty(self, temp_templates_dir: Path):
        """Empty prompt context when no templates."""
        loader = TemplateLoader(temp_templates_dir)
        loader.load_all()
        context = loader.build_classification_prompt_context()
        assert "No templates available" in context

    def test_validate_classification_result(self, loader_with_templates: TemplateLoader):
        """Validate classification result against template."""
        validated = loader_with_templates.validate_classification_result(
            "task",
            {"title": "My Task", "priority": "High"},
        )
        assert validated["title"] == "My Task"

    def test_validate_classification_result_unknown_template(self, loader_with_templates: TemplateLoader):
        """Validation fails for unknown template."""
        with pytest.raises(ValueError, match="Unknown template"):
            loader_with_templates.validate_classification_result("unknown", {})

    def test_get_fallback_template(self, loader_with_templates: TemplateLoader):
        """Get the general fallback template."""
        fallback = loader_with_templates.get_fallback_template()
        assert fallback is not None
        assert fallback.name == "general"

    def test_reload(self, temp_templates_dir: Path, sample_template_data: Dict[str, Any]):
        """Reload templates from disk."""
        # Write initial template
        with open(temp_templates_dir / "task.yaml", "w") as f:
            yaml.dump(sample_template_data, f)

        loader = TemplateLoader(temp_templates_dir)
        loader.load_all()
        assert len(loader) == 1

        # Add another template
        general_data = sample_template_data.copy()
        general_data["name"] = "general"
        general_data["display_name"] = "General"
        with open(temp_templates_dir / "general.yaml", "w") as f:
            yaml.dump(general_data, f)

        # Reload
        loader.reload()
        assert len(loader) == 2

    def test_iteration(self, loader_with_templates: TemplateLoader):
        """Iterate over templates."""
        names = [t.name for t in loader_with_templates]
        assert set(names) == {"task", "general"}

    def test_contains(self, loader_with_templates: TemplateLoader):
        """Check template containment."""
        assert "task" in loader_with_templates
        assert "nonexistent" not in loader_with_templates

    def test_len(self, loader_with_templates: TemplateLoader):
        """Get template count."""
        assert len(loader_with_templates) == 2


class TestTemplateLoaderErrorHandling:
    """Tests for error handling in TemplateLoader."""

    def test_invalid_yaml_syntax(self, temp_templates_dir: Path):
        """Handle invalid YAML syntax."""
        bad_yaml = temp_templates_dir / "bad.yaml"
        with open(bad_yaml, "w") as f:
            # This is definitely invalid YAML - unbalanced brackets
            f.write("name: [\nunmatched bracket")

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()
        assert count == 0
        assert len(loader.load_errors) == 1
        assert "Invalid YAML" in loader.load_errors[0]

    def test_empty_file(self, temp_templates_dir: Path):
        """Handle empty YAML file."""
        empty_file = temp_templates_dir / "empty.yaml"
        empty_file.touch()

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()
        assert count == 0
        assert len(loader.load_errors) == 1
        assert "empty" in loader.load_errors[0].lower()

    def test_missing_required_fields(self, temp_templates_dir: Path):
        """Handle template missing required fields."""
        incomplete = temp_templates_dir / "incomplete.yaml"
        with open(incomplete, "w") as f:
            yaml.dump({"name": "test"}, f)  # Missing display_name

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()
        assert count == 0
        assert len(loader.load_errors) == 1
        assert "display_name" in loader.load_errors[0]

    def test_duplicate_template_names(self, temp_templates_dir: Path, sample_template_data: Dict[str, Any]):
        """Handle duplicate template names."""
        # Write same template name to two files
        with open(temp_templates_dir / "task1.yaml", "w") as f:
            yaml.dump(sample_template_data, f)
        with open(temp_templates_dir / "task2.yaml", "w") as f:
            yaml.dump(sample_template_data, f)

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()
        # First one loads, second is duplicate
        assert count == 1
        assert len(loader.load_errors) == 1
        assert "Duplicate" in loader.load_errors[0]

    def test_raise_on_error_mode(self, temp_templates_dir: Path):
        """Raise exception on error in strict mode."""
        bad_yaml = temp_templates_dir / "bad.yaml"
        with open(bad_yaml, "w") as f:
            # This is definitely invalid YAML - unbalanced brackets
            f.write("name: [\nunmatched bracket")

        loader = TemplateLoader(temp_templates_dir)
        with pytest.raises(TemplateLoadError):
            loader.load_all(raise_on_error=True)

    def test_template_validation_no_fields(self, temp_templates_dir: Path):
        """Template must have at least one field."""
        no_fields = temp_templates_dir / "nofields.yaml"
        with open(no_fields, "w") as f:
            yaml.dump({
                "name": "nofields",
                "display_name": "No Fields",
                "fields": [],
            }, f)

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()
        assert count == 0
        assert "at least one field" in loader.load_errors[0]

    def test_template_validation_duplicate_field_names(self, temp_templates_dir: Path):
        """Template should not have duplicate field names."""
        dup_fields = temp_templates_dir / "dupfields.yaml"
        with open(dup_fields, "w") as f:
            yaml.dump({
                "name": "dupfields",
                "display_name": "Duplicate Fields",
                "fields": [
                    {"name": "title", "type": "title"},
                    {"name": "title", "type": "rich_text"},  # Duplicate
                ],
            }, f)

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()
        assert count == 0
        assert "Duplicate field" in loader.load_errors[0]

    def test_select_without_options_fails(self, temp_templates_dir: Path):
        """Select field without options should fail validation."""
        select_no_opts = temp_templates_dir / "select_no_opts.yaml"
        with open(select_no_opts, "w") as f:
            yaml.dump({
                "name": "select_no_opts",
                "display_name": "Select Without Options",
                "fields": [
                    {"name": "status", "type": "select"},  # No options - invalid
                ],
            }, f)

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()
        assert count == 0
        assert "no options" in loader.load_errors[0]

    def test_multi_select_without_options_ok(self, temp_templates_dir: Path):
        """Multi-select field without options should be valid (auto-creates in Notion)."""
        multi_no_opts = temp_templates_dir / "multi_no_opts.yaml"
        with open(multi_no_opts, "w") as f:
            yaml.dump({
                "name": "multi_no_opts",
                "display_name": "Multi Select Without Options",
                "fields": [
                    {"name": "tags", "type": "multi_select"},  # No options - valid for multi_select
                ],
            }, f)

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()
        assert count == 1
        assert len(loader.load_errors) == 0


class TestTemplateLoaderIntegration:
    """Integration tests for template loading."""

    def test_load_real_template_format(self, temp_templates_dir: Path):
        """Load a template matching the real YAML format from TDD."""
        task_yaml = """
name: task
display_name: Task
description: Action items, to-dos, reminders, commitments
enabled: true

triggers:
  patterns:
    - "I need to"
    - "don't forget to"
    - "remind me to"
    - "task:"
    - "todo:"
    - "action item"
  indicators:
    - imperative statements
    - action commitments
    - deadlines mentioned
    - responsibility assignments

fields:
  - name: title
    type: title
    description: Concise action item
    extraction: Extract the core action as a brief imperative statement
    required: true
    notion_property: Task

  - name: date_created
    type: date
    description: Capture timestamp
    extraction: Use capture metadata
    required: true
    notion_property: Date Created

  - name: due_date
    type: date
    description: Deadline if mentioned
    extraction: Extract explicit date/time references; leave empty if none
    required: false
    notion_property: Due Date

  - name: priority
    type: select
    description: Task priority
    extraction: Infer from urgency language; default to Medium if unclear
    options: [High, Medium, Low]
    default: Medium
    notion_property: Priority

  - name: context
    type: rich_text
    description: Why, for whom, related project
    extraction: Extract any mentioned context, stakeholders, or project references
    required: false
    notion_property: Context

  - name: status
    type: select
    description: Task status
    options: [Not Started, In Progress, Complete]
    default: Not Started
    notion_property: Status

  - name: tags
    type: multi_select
    description: Topic tags
    extraction: Generate 2-5 relevant topic tags
    notion_property: Tags

notion:
  database_id: ${NOTION_VOICE_CAPTURES_DB_ID}

page_body_template: |
  ## Context
  {{ context | default("No additional context provided.") }}

  ## Raw Transcript
  {{ transcript }}
"""
        with open(temp_templates_dir / "task.yaml", "w") as f:
            f.write(task_yaml)

        loader = TemplateLoader(temp_templates_dir)
        count = loader.load_all()

        assert count == 1
        task = loader.get_template("task")
        assert task is not None
        assert task.display_name == "Task"
        assert len(task.fields) == 7
        assert task.get_field("priority").default == "Medium"
        assert task.get_field("status").options == ["Not Started", "In Progress", "Complete"]
        assert "{{ context" in task.page_body_template
