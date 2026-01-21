"""
Comprehensive tests for the classification service.

Tests for:
- PromptBuilder: Building classification prompts from templates
- ResponseParser: Parsing and validating LLM responses
- ClassificationService: End-to-end classification with mocked API
- ClassificationConfig: Configuration loading and validation
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.classification.classification import (
    ClassificationConfig,
    ClassificationService,
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
from src.classification.template_loader import TemplateLoader
from src.models.classification import ClassificationResult


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to classification fixtures directory."""
    return Path(__file__).parent / "fixtures" / "classifications"


@pytest.fixture
def temp_templates_dir(tmp_path: Path) -> Path:
    """Create a temporary templates directory with test templates."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    # Create task template
    task_template = {
        "name": "task",
        "display_name": "Task",
        "description": "Action items, to-dos, reminders",
        "enabled": True,
        "triggers": {
            "patterns": ["I need to", "remind me", "task:"],
            "indicators": ["imperative statements", "action commitments"],
        },
        "fields": [
            {
                "name": "title",
                "type": "title",
                "description": "Task title",
                "extraction": "Extract core action",
                "required": True,
            },
            {
                "name": "priority",
                "type": "select",
                "description": "Priority level",
                "options": ["High", "Medium", "Low"],
                "default": "Medium",
            },
            {
                "name": "status",
                "type": "select",
                "description": "Task status",
                "options": ["Not Started", "In Progress", "Complete"],
                "default": "Not Started",
            },
        ],
        "notion": {"database_id": "test-db"},
        "page_body_template": "{{ title }}",
    }
    with open(templates_dir / "task.yaml", "w") as f:
        yaml.dump(task_template, f)

    # Create general template (fallback)
    general_template = {
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
                "description": "Summary",
            },
        ],
        "notion": {"database_id": "test-db"},
        "page_body_template": "{{ summary }}",
    }
    with open(templates_dir / "general.yaml", "w") as f:
        yaml.dump(general_template, f)

    return templates_dir


@pytest.fixture
def template_loader(temp_templates_dir: Path) -> TemplateLoader:
    """Create a template loader with test templates loaded."""
    loader = TemplateLoader(temp_templates_dir)
    loader.load_all()
    return loader


@pytest.fixture
def temp_config_file(tmp_path: Path) -> Path:
    """Create a temporary classification config file."""
    config_path = tmp_path / "classification.yaml"
    config_data = {
        "confidence_threshold": 0.7,
        "fallback_template": "general",
        "template_priority": ["task", "journal"],
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2048,
        "max_retries": 3,
        "base_backoff_seconds": 5.0,
        "system_context": "Test context for classification.",
    }
    with open(config_path, "w") as f:
        yaml.dump(config_data, f)
    return config_path


@pytest.fixture
def mock_anthropic_client():
    """Create a mock Anthropic client."""
    client = MagicMock()
    return client


@pytest.fixture
def sample_task_response() -> str:
    """Sample successful task classification response."""
    return json.dumps({
        "template": "task",
        "confidence": 0.92,
        "reasoning": "Clear imperative statement with deadline.",
        "title": "Review quarterly report by Friday",
        "tags": ["work", "report"],
        "fields": {
            "title": "Review quarterly report by Friday",
            "priority": "High",
            "status": "Not Started",
        },
    })


# =============================================================================
# TranscriptMetadata Tests
# =============================================================================


class TestTranscriptMetadata:
    """Tests for TranscriptMetadata dataclass."""

    def test_default_values(self):
        """Create metadata with defaults."""
        metadata = TranscriptMetadata()
        assert metadata.captured_at is None
        assert metadata.duration_seconds is None
        assert metadata.device == "unknown"

    def test_with_all_values(self):
        """Create metadata with all values set."""
        now = datetime.now()
        metadata = TranscriptMetadata(
            captured_at=now,
            duration_seconds=45.5,
            device="watch",
        )
        assert metadata.captured_at == now
        assert metadata.duration_seconds == 45.5
        assert metadata.device == "watch"

    def test_format_for_prompt(self):
        """Format metadata for prompt inclusion."""
        metadata = TranscriptMetadata(
            captured_at=datetime(2026, 1, 20, 14, 30, 22),
            duration_seconds=45.5,
            device="watch",
        )
        formatted = metadata.format_for_prompt()

        assert "2026-01-20 14:30:22" in formatted
        assert "45.5 seconds" in formatted
        assert "Watch" in formatted

    def test_format_for_prompt_with_unknowns(self):
        """Format metadata with unknown values."""
        metadata = TranscriptMetadata()
        formatted = metadata.format_for_prompt()

        assert "Unknown time" in formatted
        assert "Unknown" in formatted


# =============================================================================
# PromptBuilder Tests
# =============================================================================


class TestPromptBuilder:
    """Tests for PromptBuilder class."""

    def test_build_basic_prompt(self, template_loader: TemplateLoader):
        """Build a basic classification prompt."""
        builder = PromptBuilder(template_loader)
        prompt = builder.build_classification_prompt(
            transcript="I need to review the report by Friday.",
        )

        # Check all sections are present
        assert "classifying and structuring voice capture" in prompt
        assert "## Available Templates" in prompt
        assert "## Classification Rules" in prompt
        assert "## Overlap Handling" in prompt
        assert "## Transcript Metadata" in prompt
        assert "## Transcript" in prompt
        assert "## Response Format" in prompt

        # Check transcript is included
        assert "review the report by Friday" in prompt

    def test_build_prompt_with_metadata(self, template_loader: TemplateLoader):
        """Build prompt with transcript metadata."""
        builder = PromptBuilder(template_loader)
        metadata = TranscriptMetadata(
            captured_at=datetime(2026, 1, 20, 14, 30, 0),
            duration_seconds=30.0,
            device="phone",
        )
        prompt = builder.build_classification_prompt(
            transcript="Test transcript",
            metadata=metadata,
        )

        assert "2026-01-20" in prompt
        assert "30.0 seconds" in prompt
        assert "Phone" in prompt

    def test_build_prompt_with_system_context(self, template_loader: TemplateLoader):
        """Build prompt with custom system context."""
        builder = PromptBuilder(
            template_loader,
            system_context="Custom context for testing.",
        )
        prompt = builder.build_classification_prompt("Test transcript")

        assert "Custom context for testing" in prompt

    def test_build_prompt_with_custom_threshold(self, template_loader: TemplateLoader):
        """Build prompt with custom confidence threshold."""
        builder = PromptBuilder(
            template_loader,
            confidence_threshold=0.8,
        )
        prompt = builder.build_classification_prompt("Test transcript")

        assert "0.8" in prompt

    def test_prompt_includes_template_definitions(self, template_loader: TemplateLoader):
        """Prompt includes template definitions from loader."""
        builder = PromptBuilder(template_loader)
        prompt = builder.build_classification_prompt("Test transcript")

        assert "### Task" in prompt
        assert "### General" in prompt
        assert "Action items" in prompt

    def test_corrective_prompt(self):
        """Build corrective prompt for JSON errors."""
        prompt = build_corrective_prompt(
            original_response="{ invalid json",
            error_message="Expecting property name",
        )

        assert "not valid JSON" in prompt
        assert "Expecting property name" in prompt
        assert "{ invalid json" in prompt
        assert "valid JSON object" in prompt


# =============================================================================
# ResponseParser Tests
# =============================================================================


class TestResponseParser:
    """Tests for ResponseParser class."""

    def test_parse_valid_response(self, template_loader: TemplateLoader):
        """Parse a valid JSON response."""
        parser = ResponseParser(template_loader)
        response = json.dumps({
            "template": "task",
            "confidence": 0.85,
            "reasoning": "Clear task description.",
            "title": "Review report",
            "tags": ["work"],
            "fields": {"title": "Review report", "priority": "High"},
        })

        result = parser.parse(response)

        assert result.template_name == "task"
        assert result.confidence == 0.85
        assert result.title == "Review report"
        assert result.tags == ["work"]
        assert result.fields["title"] == "Review report"

    def test_parse_response_in_code_block(
        self, template_loader: TemplateLoader, fixtures_dir: Path
    ):
        """Parse JSON wrapped in markdown code block."""
        parser = ResponseParser(template_loader)
        response = (fixtures_dir / "json_in_code_block.txt").read_text()

        result = parser.parse(response)

        assert result.template_name == "task"
        assert result.confidence == 0.85

    def test_parse_invalid_json(self, template_loader: TemplateLoader, fixtures_dir: Path):
        """Raise ParseError for invalid JSON."""
        parser = ResponseParser(template_loader)
        response = (fixtures_dir / "invalid_json.txt").read_text()

        with pytest.raises(ParseError) as exc_info:
            parser.parse(response)

        assert "Could not extract JSON" in str(exc_info.value)

    def test_parse_malformed_fields(self, template_loader: TemplateLoader):
        """Handle malformed field values gracefully."""
        parser = ResponseParser(template_loader)
        response = json.dumps({
            "template": "task",
            "confidence": "0.85",  # String instead of number - should work
            "title": "Test",
            "tags": [],
            "fields": {},
        })

        result = parser.parse(response)
        assert result.confidence == 0.85  # Should be converted to float

    def test_parse_missing_confidence(self, template_loader: TemplateLoader):
        """Raise error for missing confidence."""
        parser = ResponseParser(template_loader)
        response = json.dumps({
            "template": "task",
            "title": "Test",
            "tags": [],
            "fields": {},
        })

        with pytest.raises(ParseError) as exc_info:
            parser.parse(response)

        assert "confidence" in str(exc_info.value)

    def test_parse_invalid_confidence_range(self, template_loader: TemplateLoader):
        """Raise error for confidence out of range."""
        parser = ResponseParser(template_loader)
        response = json.dumps({
            "template": "task",
            "confidence": 1.5,  # Out of range
            "title": "Test",
            "tags": [],
            "fields": {},
        })

        with pytest.raises(ValidationError) as exc_info:
            parser.parse(response)

        assert "0.0 and 1.0" in str(exc_info.value)

    def test_parse_unknown_template_uses_fallback(self, template_loader: TemplateLoader):
        """Unknown template should fall back to general."""
        parser = ResponseParser(template_loader)
        response = json.dumps({
            "template": "unknown_template",
            "confidence": 0.85,
            "title": "Test",
            "tags": [],
            "fields": {},
        })

        result = parser.parse(response)
        assert result.template_name == "general"

    def test_parse_low_confidence_falls_back(self, template_loader: TemplateLoader):
        """Low confidence should trigger fallback to general."""
        parser = ResponseParser(template_loader, confidence_threshold=0.7)
        response = json.dumps({
            "template": "task",
            "confidence": 0.55,  # Below threshold
            "reasoning": "Ambiguous content",
            "title": "Maybe a task",
            "tags": ["misc"],
            "fields": {"title": "Maybe a task"},
        })

        result = parser.parse(response)

        assert result.template_name == "general"
        assert result.confidence == 0.55  # Original confidence preserved
        assert "fell back to" in result.reasoning

    def test_parse_normalizes_tags(self, template_loader: TemplateLoader):
        """Tags should be normalized (lowercase, unique)."""
        parser = ResponseParser(template_loader)
        response = json.dumps({
            "template": "task",
            "confidence": 0.85,
            "title": "Test",
            "tags": ["Work", "URGENT", "work", "Personal", None],  # Dups and None
            "fields": {},
        })

        result = parser.parse(response)

        assert "work" in result.tags
        assert "urgent" in result.tags
        assert "personal" in result.tags
        assert len(result.tags) == 3  # Duplicates removed

    def test_parse_applies_field_defaults(self, template_loader: TemplateLoader):
        """Missing optional fields should use defaults."""
        parser = ResponseParser(template_loader)
        response = json.dumps({
            "template": "task",
            "confidence": 0.85,
            "title": "Test task",
            "tags": [],
            "fields": {"title": "Test task"},  # Missing priority and status
        })

        result = parser.parse(response)

        assert result.fields.get("priority") == "Medium"  # Default
        assert result.fields.get("status") == "Not Started"  # Default


class TestCreateFallbackResult:
    """Tests for create_fallback_result function."""

    def test_creates_fallback_with_short_transcript(self):
        """Create fallback for short transcript."""
        result = create_fallback_result(
            transcript="This is a short transcript.",
            reason="Test fallback",
        )

        assert result.template_name == "general"
        assert result.confidence == 0.0
        assert result.title == "This is a short transcript"
        assert "Test fallback" in result.reasoning

    def test_creates_fallback_with_long_transcript(self):
        """Create fallback for long transcript - title truncated."""
        long_text = "A" * 100 + ". More text here."
        result = create_fallback_result(transcript=long_text)

        assert len(result.title) <= 63  # 60 chars + "..."
        assert result.title.endswith("...")

    def test_creates_fallback_with_empty_transcript(self):
        """Create fallback for empty transcript."""
        result = create_fallback_result(transcript="")

        assert result.title == "Untitled capture"


# =============================================================================
# ClassificationConfig Tests
# =============================================================================


class TestClassificationConfig:
    """Tests for ClassificationConfig class."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = ClassificationConfig()

        assert config.confidence_threshold == 0.7
        assert config.fallback_template == "general"
        assert config.model == "claude-sonnet-4-20250514"
        assert config.max_tokens == 2048
        assert config.max_retries == 3

    def test_load_from_file(self, temp_config_file: Path):
        """Load config from YAML file."""
        config = ClassificationConfig.from_file(temp_config_file)

        assert config.confidence_threshold == 0.7
        assert config.template_priority == ["task", "journal"]
        assert config.system_context == "Test context for classification."

    def test_load_from_missing_file(self, tmp_path: Path):
        """Return defaults for missing config file."""
        config = ClassificationConfig.from_file(tmp_path / "nonexistent.yaml")

        assert config.confidence_threshold == 0.7
        assert config.fallback_template == "general"

    def test_backoff_calculation(self):
        """Calculate exponential backoff with jitter."""
        config = ClassificationConfig(
            base_backoff_seconds=5.0,
            max_backoff_seconds=300.0,
            backoff_multiplier=2.0,
        )

        # First retry
        backoff_0 = config.get_backoff(0)
        assert 5.0 <= backoff_0 <= 5.5  # Base + up to 10% jitter

        # Second retry
        backoff_1 = config.get_backoff(1)
        assert 10.0 <= backoff_1 <= 11.0  # 5 * 2 + jitter

        # Third retry
        backoff_2 = config.get_backoff(2)
        assert 20.0 <= backoff_2 <= 22.0  # 5 * 4 + jitter

        # Cap at max
        backoff_high = config.get_backoff(10)
        assert backoff_high <= 330.0  # 300 + 10% jitter


# =============================================================================
# ClassificationService Tests
# =============================================================================


class TestClassificationService:
    """Tests for ClassificationService class."""

    @pytest.mark.asyncio
    async def test_classify_success(
        self,
        template_loader: TemplateLoader,
        mock_anthropic_client,
        sample_task_response: str,
    ):
        """Successful classification returns result."""
        # Setup mock
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=sample_task_response)]
        mock_anthropic_client.messages.create = MagicMock(return_value=mock_response)

        service = ClassificationService(
            anthropic_client=mock_anthropic_client,
            template_loader=template_loader,
        )

        result = await service.classify("I need to review the quarterly report by Friday")

        assert result.template_name == "task"
        assert result.confidence == 0.92
        assert "report" in result.title.lower()

    @pytest.mark.asyncio
    async def test_classify_empty_transcript(
        self,
        template_loader: TemplateLoader,
        mock_anthropic_client,
    ):
        """Empty transcript returns fallback."""
        service = ClassificationService(
            anthropic_client=mock_anthropic_client,
            template_loader=template_loader,
        )

        result = await service.classify("")

        assert result.template_name == "general"
        assert result.confidence == 0.0
        assert "Empty transcript" in result.reasoning

    @pytest.mark.asyncio
    async def test_classify_api_failure_returns_fallback(
        self,
        template_loader: TemplateLoader,
        mock_anthropic_client,
    ):
        """API failure after retries returns fallback."""
        mock_anthropic_client.messages.create = MagicMock(
            side_effect=Exception("API Error")
        )

        config = ClassificationConfig(max_retries=2, base_backoff_seconds=0.01)
        service = ClassificationService(
            anthropic_client=mock_anthropic_client,
            template_loader=template_loader,
            config=config,
        )

        result = await service.classify("Some transcript text")

        assert result.template_name == "general"
        assert result.confidence == 0.0
        assert "API call failed" in result.reasoning

    @pytest.mark.asyncio
    async def test_classify_retries_on_failure(
        self,
        template_loader: TemplateLoader,
        mock_anthropic_client,
        sample_task_response: str,
    ):
        """Service retries on transient failures."""
        # First two calls fail, third succeeds
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=sample_task_response)]

        mock_anthropic_client.messages.create = MagicMock(
            side_effect=[
                Exception("Transient error 1"),
                Exception("Transient error 2"),
                mock_response,
            ]
        )

        config = ClassificationConfig(max_retries=3, base_backoff_seconds=0.01)
        service = ClassificationService(
            anthropic_client=mock_anthropic_client,
            template_loader=template_loader,
            config=config,
        )

        result = await service.classify("I need to review the report")

        assert result.template_name == "task"
        assert mock_anthropic_client.messages.create.call_count == 3

    @pytest.mark.asyncio
    async def test_classify_with_metadata(
        self,
        template_loader: TemplateLoader,
        mock_anthropic_client,
        sample_task_response: str,
    ):
        """Classification includes metadata in prompt."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=sample_task_response)]
        mock_anthropic_client.messages.create = MagicMock(return_value=mock_response)

        service = ClassificationService(
            anthropic_client=mock_anthropic_client,
            template_loader=template_loader,
        )

        metadata = TranscriptMetadata(
            captured_at=datetime(2026, 1, 20, 14, 30, 0),
            duration_seconds=45.0,
            device="watch",
        )

        result = await service.classify("Test transcript", metadata=metadata)

        # Verify the prompt included metadata
        call_args = mock_anthropic_client.messages.create.call_args
        messages = call_args.kwargs["messages"]
        prompt = messages[0]["content"]

        assert "2026-01-20" in prompt
        assert "45.0" in prompt
        assert "Watch" in prompt

    def test_classify_sync_wrapper(
        self,
        template_loader: TemplateLoader,
        mock_anthropic_client,
        sample_task_response: str,
    ):
        """Synchronous classify_sync works correctly."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=sample_task_response)]
        mock_anthropic_client.messages.create = MagicMock(return_value=mock_response)

        service = ClassificationService(
            anthropic_client=mock_anthropic_client,
            template_loader=template_loader,
        )

        result = service.classify_sync("I need to review the report")

        assert result.template_name == "task"


# =============================================================================
# Integration Tests with Real Templates
# =============================================================================


class TestClassificationIntegration:
    """Integration tests using real template files."""

    @pytest.fixture
    def real_template_loader(self) -> TemplateLoader:
        """Load actual templates from config/templates/."""
        templates_path = Path(__file__).parent.parent / "config" / "templates"
        if not templates_path.exists():
            pytest.skip("Real templates not available")

        loader = TemplateLoader(templates_path)
        loader.load_all()
        return loader

    def test_prompt_builder_with_real_templates(self, real_template_loader: TemplateLoader):
        """Build prompt with real template definitions."""
        builder = PromptBuilder(real_template_loader)
        prompt = builder.build_classification_prompt(
            transcript="I need to schedule a meeting with the client about the Q1 review."
        )

        # Check all real templates are included
        assert "### Task" in prompt
        assert "### Journal" in prompt
        assert "### Idea" in prompt
        assert "### Research" in prompt
        assert "### Product" in prompt
        assert "### General" in prompt

    def test_response_parser_with_fixture_responses(
        self, real_template_loader: TemplateLoader, fixtures_dir: Path
    ):
        """Parse fixture responses with real templates."""
        parser = ResponseParser(real_template_loader)

        # Test high confidence task
        task_response = (fixtures_dir / "task_high_confidence.json").read_text()
        result = parser.parse(task_response)
        assert result.template_name == "task"
        assert result.confidence >= 0.7

        # Test journal
        journal_response = (fixtures_dir / "journal_high_confidence.json").read_text()
        result = parser.parse(journal_response)
        assert result.template_name == "journal"

        # Test low confidence falls back
        low_conf_response = (fixtures_dir / "task_low_confidence.json").read_text()
        result = parser.parse(low_conf_response)
        assert result.template_name == "general"  # Falls back due to low confidence


# =============================================================================
# Load Config Tests
# =============================================================================


class TestLoadClassificationConfig:
    """Tests for load_classification_config function."""

    def test_load_default_path(self, monkeypatch, tmp_path: Path):
        """Load from default path."""
        # Change to temp directory
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "classification.yaml"
        config_file.write_text("confidence_threshold: 0.8")

        monkeypatch.chdir(tmp_path)

        config = load_classification_config()
        # Will read from the config file we created
        assert config.confidence_threshold == 0.8

    def test_load_custom_path(self, temp_config_file: Path):
        """Load from custom path."""
        config = load_classification_config(temp_config_file)
        assert config.confidence_threshold == 0.7
