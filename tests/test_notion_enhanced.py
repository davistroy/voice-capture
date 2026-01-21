"""Tests for enhanced Notion integration (Phase 2).

Tests cover:
- PropertyMapper: all field type mappings
- ContentBuilder: Jinja2 template rendering
- NotionService: template-specific page creation
"""

import json
from datetime import datetime, date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.notion.property_mapper import (
    PropertyMapper,
    PropertyMappingError,
    create_device_property,
    create_type_property,
)
from src.notion.content_builder import (
    ContentBuilder,
    ContentBuildError,
    MAX_TRANSCRIPT_LENGTH,
    TRUNCATION_INDICATOR,
)
from src.notion.client import NotionService, NotionPage, CaptureMetadata
from src.models.transcription import TranscriptionResult
from src.models.classification import ClassificationResult
from src.classification.template_config import (
    TemplateConfig,
    FieldConfig,
    FieldType,
    TriggersConfig,
)


# ============================================================================
# Fixtures
# ============================================================================

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "api_responses"


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file."""
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture
def notion_success_response():
    """Load successful Notion page creation response."""
    return load_fixture("notion_success.json")


@pytest.fixture
def sample_metadata():
    """Create sample capture metadata."""
    return CaptureMetadata(
        captured_at=datetime(2026, 1, 20, 14, 30, 22),
        device="watch",
        duration_seconds=15.5,
    )


@pytest.fixture
def sample_transcription():
    """Create a sample transcription result."""
    return TranscriptionResult(
        text="I need to review the quarterly report by Friday. This is important for the client meeting.",
        duration_seconds=15.5,
        language="en",
        segments=None,
    )


@pytest.fixture
def task_template():
    """Create a sample task template configuration."""
    return TemplateConfig(
        name="task",
        display_name="Task",
        description="Action items and to-dos",
        enabled=True,
        triggers=TriggersConfig(
            patterns=["I need to", "remind me"],
            indicators=["imperative statements"],
        ),
        fields=[
            FieldConfig(
                name="title",
                type=FieldType.TITLE,
                description="Task title",
                required=True,
                notion_property="Task",
            ),
            FieldConfig(
                name="date_created",
                type=FieldType.DATE,
                description="Creation date",
                required=True,
                notion_property="Date Created",
            ),
            FieldConfig(
                name="due_date",
                type=FieldType.DATE,
                description="Due date",
                required=False,
                notion_property="Due Date",
            ),
            FieldConfig(
                name="priority",
                type=FieldType.SELECT,
                description="Priority level",
                required=False,
                default="Medium",
                options=["High", "Medium", "Low"],
                notion_property="Priority",
            ),
            FieldConfig(
                name="context",
                type=FieldType.RICH_TEXT,
                description="Additional context",
                required=False,
                notion_property="Context",
            ),
            FieldConfig(
                name="status",
                type=FieldType.SELECT,
                description="Task status",
                required=False,
                default="Not Started",
                options=["Not Started", "In Progress", "Complete"],
                notion_property="Status",
            ),
            FieldConfig(
                name="tags",
                type=FieldType.MULTI_SELECT,
                description="Tags",
                required=False,
                notion_property="Tags",
            ),
        ],
        notion_database_id="test-db-id",
        page_body_template="""## Context
{{ context | default("No additional context provided.") }}

{% if due_date %}
## Due Date
{{ due_date }}
{% endif %}

## Raw Transcript
{{ transcript }}

---
*Processed: {{ processed_at }} | Device: {{ device }} | Duration: {{ duration }}s*
""",
    )


@pytest.fixture
def task_classification():
    """Create a sample task classification result."""
    return ClassificationResult(
        template_name="task",
        confidence=0.85,
        fields={
            "title": "Review quarterly report",
            "date_created": "2026-01-20T14:30:22",
            "due_date": "2026-01-24",
            "priority": "High",
            "context": "Important for the client meeting",
            "status": "Not Started",
        },
        title="Review quarterly report by Friday",
        tags=["work", "urgent", "quarterly-review"],
        reasoning="Task identified from imperative language and deadline mention",
    )


@pytest.fixture
def journal_template():
    """Create a sample journal template configuration."""
    return TemplateConfig(
        name="journal",
        display_name="Journal",
        description="Personal reflections",
        enabled=True,
        triggers=TriggersConfig(
            patterns=["today I", "feeling"],
            indicators=["first-person narrative"],
        ),
        fields=[
            FieldConfig(
                name="title",
                type=FieldType.TITLE,
                description="Entry title",
                required=True,
                notion_property="Title",
            ),
            FieldConfig(
                name="date",
                type=FieldType.DATE,
                description="Entry date",
                required=True,
                notion_property="Date",
            ),
            FieldConfig(
                name="mood",
                type=FieldType.SELECT,
                description="Mood",
                required=False,
                default="Neutral",
                options=["Energized", "Focused", "Neutral", "Tired", "Frustrated"],
                notion_property="Mood",
            ),
            FieldConfig(
                name="summary",
                type=FieldType.RICH_TEXT,
                description="Summary",
                required=True,
                notion_property="Summary",
            ),
            FieldConfig(
                name="people_mentioned",
                type=FieldType.MULTI_SELECT,
                description="People mentioned",
                required=False,
                notion_property="People Mentioned",
            ),
        ],
        notion_database_id="test-db-id",
        page_body_template="""## Summary
{{ summary | default("No summary provided.") }}

## Full Entry
{{ full_entry | default(transcript) }}

{% if people_mentioned %}
## People Mentioned
{{ people_mentioned | join(", ") }}
{% endif %}

## Raw Transcript
{{ transcript }}

---
*Processed: {{ processed_at }} | Device: {{ device }} | Duration: {{ duration }}s*
""",
    )


# ============================================================================
# PropertyMapper Tests
# ============================================================================

class TestPropertyMapper:
    """Tests for PropertyMapper class."""

    def test_map_title_property(self):
        """Test mapping title field type."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="title",
            type=FieldType.TITLE,
            notion_property="Title",
        )

        result = mapper.map_field_to_property(field_config, "My Task Title")

        assert result == {
            "title": [{"text": {"content": "My Task Title"}}]
        }

    def test_map_title_property_empty(self):
        """Test mapping empty title returns empty string."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="title",
            type=FieldType.TITLE,
            notion_property="Title",
        )

        result = mapper.map_field_to_property(field_config, "")

        assert result == {
            "title": [{"text": {"content": ""}}]
        }

    def test_map_date_property_datetime(self):
        """Test mapping datetime object to date property."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="date",
            type=FieldType.DATE,
            notion_property="Date",
        )

        dt = datetime(2026, 1, 20, 14, 30, 22)
        result = mapper.map_field_to_property(field_config, dt)

        assert result == {
            "date": {"start": "2026-01-20T14:30:22"}
        }

    def test_map_date_property_date_object(self):
        """Test mapping date object to date property."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="date",
            type=FieldType.DATE,
            notion_property="Date",
        )

        d = date(2026, 1, 20)
        result = mapper.map_field_to_property(field_config, d)

        assert result == {
            "date": {"start": "2026-01-20"}
        }

    def test_map_date_property_iso_string(self):
        """Test mapping ISO 8601 string to date property."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="date",
            type=FieldType.DATE,
            notion_property="Date",
        )

        result = mapper.map_field_to_property(field_config, "2026-01-24")

        assert result == {
            "date": {"start": "2026-01-24"}
        }

    def test_map_date_property_empty_raises(self):
        """Test mapping empty date raises error."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="date",
            type=FieldType.DATE,
            notion_property="Date",
        )

        with pytest.raises(PropertyMappingError) as exc_info:
            mapper.map_field_to_property(field_config, "")

        assert "cannot be empty" in str(exc_info.value)

    def test_map_select_property(self):
        """Test mapping select field type."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="priority",
            type=FieldType.SELECT,
            options=["High", "Medium", "Low"],
            notion_property="Priority",
        )

        result = mapper.map_field_to_property(field_config, "High")

        assert result == {
            "select": {"name": "High"}
        }

    def test_map_select_property_empty_raises(self):
        """Test mapping empty select raises error."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="priority",
            type=FieldType.SELECT,
            options=["High", "Medium", "Low"],
            notion_property="Priority",
        )

        with pytest.raises(PropertyMappingError):
            mapper.map_field_to_property(field_config, "")

    def test_map_multi_select_property_list(self):
        """Test mapping list to multi_select property."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="tags",
            type=FieldType.MULTI_SELECT,
            notion_property="Tags",
        )

        result = mapper.map_field_to_property(field_config, ["work", "urgent"])

        assert result == {
            "multi_select": [
                {"name": "work"},
                {"name": "urgent"},
            ]
        }

    def test_map_multi_select_property_comma_string(self):
        """Test mapping comma-separated string to multi_select."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="tags",
            type=FieldType.MULTI_SELECT,
            notion_property="Tags",
        )

        result = mapper.map_field_to_property(field_config, "work, urgent, client")

        assert result == {
            "multi_select": [
                {"name": "work"},
                {"name": "urgent"},
                {"name": "client"},
            ]
        }

    def test_map_multi_select_empty_list(self):
        """Test mapping empty list to multi_select."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="tags",
            type=FieldType.MULTI_SELECT,
            notion_property="Tags",
        )

        result = mapper.map_field_to_property(field_config, [])

        assert result == {"multi_select": []}

    def test_map_rich_text_property(self):
        """Test mapping rich_text field type."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="context",
            type=FieldType.RICH_TEXT,
            notion_property="Context",
        )

        result = mapper.map_field_to_property(field_config, "This is the context text.")

        assert result == {
            "rich_text": [{"type": "text", "text": {"content": "This is the context text."}}]
        }

    def test_map_rich_text_long_text_splits(self):
        """Test rich_text splits long text into chunks."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="context",
            type=FieldType.RICH_TEXT,
            notion_property="Context",
        )

        # Create text longer than 2000 chars
        long_text = "A" * 2500

        result = mapper.map_field_to_property(field_config, long_text)

        # Should be split into 2 chunks
        assert len(result["rich_text"]) == 2
        assert len(result["rich_text"][0]["text"]["content"]) == 2000
        assert len(result["rich_text"][1]["text"]["content"]) == 500

    def test_map_number_property(self):
        """Test mapping number field type."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="duration",
            type=FieldType.NUMBER,
            notion_property="Duration",
        )

        result = mapper.map_field_to_property(field_config, 42.5)

        assert result == {"number": 42.5}

    def test_map_number_property_from_string(self):
        """Test mapping string number to number property."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="duration",
            type=FieldType.NUMBER,
            notion_property="Duration",
        )

        result = mapper.map_field_to_property(field_config, "42.5")

        assert result == {"number": 42.5}

    def test_map_number_property_invalid_raises(self):
        """Test mapping invalid number raises error."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="duration",
            type=FieldType.NUMBER,
            notion_property="Duration",
        )

        with pytest.raises(PropertyMappingError):
            mapper.map_field_to_property(field_config, "not a number")

    def test_map_checkbox_property_true(self):
        """Test mapping true checkbox."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="completed",
            type=FieldType.CHECKBOX,
            notion_property="Completed",
        )

        result = mapper.map_field_to_property(field_config, True)

        assert result == {"checkbox": True}

    def test_map_checkbox_property_false(self):
        """Test mapping false checkbox."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="completed",
            type=FieldType.CHECKBOX,
            notion_property="Completed",
        )

        result = mapper.map_field_to_property(field_config, False)

        assert result == {"checkbox": False}

    def test_map_checkbox_property_string_true(self):
        """Test mapping 'true' string to checkbox."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="completed",
            type=FieldType.CHECKBOX,
            notion_property="Completed",
        )

        result = mapper.map_field_to_property(field_config, "true")

        assert result == {"checkbox": True}

    def test_map_checkbox_property_string_false(self):
        """Test mapping 'false' string to checkbox."""
        mapper = PropertyMapper()
        field_config = FieldConfig(
            name="completed",
            type=FieldType.CHECKBOX,
            notion_property="Completed",
        )

        result = mapper.map_field_to_property(field_config, "false")

        assert result == {"checkbox": False}

    def test_map_fields_to_properties_full(self, task_template, task_classification):
        """Test mapping multiple fields to properties."""
        mapper = PropertyMapper()

        properties = mapper.map_fields_to_properties(
            fields=task_classification.fields,
            field_configs=task_template.fields,
            apply_defaults=True,
        )

        # Check that fields are mapped with correct property names
        assert "Task" in properties  # title -> Task
        assert "Date Created" in properties
        assert "Due Date" in properties
        assert "Priority" in properties
        assert "Context" in properties
        assert "Status" in properties

        # Check property values
        assert properties["Task"]["title"][0]["text"]["content"] == "Review quarterly report"
        assert properties["Priority"]["select"]["name"] == "High"

    def test_map_fields_applies_defaults(self):
        """Test that defaults are applied for missing fields."""
        mapper = PropertyMapper()

        fields = {"title": "My Task"}  # Only title provided

        field_configs = [
            FieldConfig(name="title", type=FieldType.TITLE, required=True),
            FieldConfig(
                name="priority",
                type=FieldType.SELECT,
                default="Medium",
                options=["High", "Medium", "Low"],
            ),
        ]

        properties = mapper.map_fields_to_properties(
            fields=fields,
            field_configs=field_configs,
            apply_defaults=True,
        )

        assert "priority" in properties
        assert properties["priority"]["select"]["name"] == "Medium"

    def test_map_fields_skips_none_values(self):
        """Test that None values are skipped."""
        mapper = PropertyMapper()

        fields = {"title": "My Task", "context": None}

        field_configs = [
            FieldConfig(name="title", type=FieldType.TITLE, required=True),
            FieldConfig(name="context", type=FieldType.RICH_TEXT, required=False),
        ]

        properties = mapper.map_fields_to_properties(
            fields=fields,
            field_configs=field_configs,
        )

        assert "title" in properties
        assert "context" not in properties


class TestDeviceAndTypeProperties:
    """Tests for device and type property helper functions."""

    def test_create_device_property_watch(self):
        """Test device property for watch."""
        result = create_device_property("watch")
        assert result == {"select": {"name": "Watch"}}

    def test_create_device_property_phone(self):
        """Test device property for phone."""
        result = create_device_property("phone")
        assert result == {"select": {"name": "Phone"}}

    def test_create_device_property_unknown(self):
        """Test device property for unknown."""
        result = create_device_property("other")
        assert result == {"select": {"name": "Unknown"}}

    def test_create_device_property_uppercase(self):
        """Test device property handles uppercase."""
        result = create_device_property("WATCH")
        assert result == {"select": {"name": "Watch"}}

    def test_create_type_property(self):
        """Test type property creation."""
        result = create_type_property("Task")
        assert result == {"select": {"name": "Task"}}

    def test_create_type_property_journal(self):
        """Test type property for journal."""
        result = create_type_property("Journal")
        assert result == {"select": {"name": "Journal"}}


# ============================================================================
# ContentBuilder Tests
# ============================================================================

class TestContentBuilder:
    """Tests for ContentBuilder class."""

    def test_build_basic_page_content(self):
        """Test basic page content generation."""
        builder = ContentBuilder()
        processed_at = datetime(2026, 1, 20, 14, 30, 22)

        content = builder.build_basic_page_content(
            transcript="This is a test transcript.",
            processed_at=processed_at,
            device="watch",
            duration_seconds=15.5,
        )

        # Should have 6 blocks: summary heading, summary, transcript heading,
        # transcript, divider, footer
        assert len(content) == 6

        # Check structure
        assert content[0]["type"] == "heading_2"
        assert content[0]["heading_2"]["rich_text"][0]["text"]["content"] == "Summary"
        assert content[1]["type"] == "paragraph"
        assert content[2]["type"] == "heading_2"
        assert content[2]["heading_2"]["rich_text"][0]["text"]["content"] == "Raw Transcript"
        assert content[3]["type"] == "paragraph"
        assert content[4]["type"] == "divider"
        assert content[5]["type"] == "paragraph"

    def test_build_basic_page_content_with_summary(self):
        """Test basic page content with provided summary."""
        builder = ContentBuilder()
        processed_at = datetime(2026, 1, 20, 14, 30, 22)

        content = builder.build_basic_page_content(
            transcript="Full transcript here.",
            processed_at=processed_at,
            device="phone",
            duration_seconds=30.0,
            summary="Custom summary text.",
        )

        # Check summary block has custom text
        summary_text = content[1]["paragraph"]["rich_text"][0]["text"]["content"]
        assert summary_text == "Custom summary text."

    def test_build_page_content_jinja2(self, task_template, task_classification):
        """Test Jinja2 template rendering for page content."""
        builder = ContentBuilder()
        processed_at = datetime(2026, 1, 20, 14, 30, 22)

        content = builder.build_page_content(
            page_body_template=task_template.page_body_template,
            fields=task_classification.fields,
            transcript="Original transcript text.",
            processed_at=processed_at,
            device="watch",
            duration_seconds=15.5,
        )

        # Content should be generated from template
        assert len(content) > 0

        # Check that content includes expected sections
        block_texts = []
        for block in content:
            if block["type"] == "heading_2":
                block_texts.append(block["heading_2"]["rich_text"][0]["text"]["content"])
            elif block["type"] == "paragraph":
                text = block["paragraph"]["rich_text"][0]["text"]["content"]
                block_texts.append(text)

        # Should have Context, Due Date, Raw Transcript sections
        assert "Context" in block_texts
        assert "Due Date" in block_texts
        assert "Raw Transcript" in block_texts

    def test_build_page_content_default_filter(self):
        """Test Jinja2 default filter works for custom fields.

        Note: The 'summary' field has special handling in _prepare_context
        that provides a fallback from the transcript. This test uses a
        different field name to verify Jinja2 default filter works.
        """
        builder = ContentBuilder()
        processed_at = datetime(2026, 1, 20, 14, 30, 22)

        # Use 'custom_field' which won't have special context handling
        template = """## Custom Section
{{ custom_field | default("Default value here") }}

## Raw Transcript
{{ transcript }}
"""

        content = builder.build_page_content(
            page_body_template=template,
            fields={},  # No custom_field
            transcript="Test transcript.",
            processed_at=processed_at,
            device="watch",
            duration_seconds=10.0,
        )

        # Find paragraph with default value
        default_found = False
        for block in content:
            if block["type"] == "paragraph":
                text = block["paragraph"]["rich_text"][0]["text"]["content"]
                if "Default value here" in text:
                    default_found = True
                    break

        assert default_found

    def test_build_page_content_conditional(self):
        """Test Jinja2 conditional blocks."""
        builder = ContentBuilder()
        processed_at = datetime(2026, 1, 20, 14, 30, 22)

        template = """## Summary
{{ summary | default("No summary") }}

{% if due_date %}
## Due Date
{{ due_date }}
{% endif %}

## Raw Transcript
{{ transcript }}
"""

        # Without due_date
        content_without = builder.build_page_content(
            page_body_template=template,
            fields={},
            transcript="Test.",
            processed_at=processed_at,
            device="watch",
            duration_seconds=10.0,
        )

        # With due_date
        content_with = builder.build_page_content(
            page_body_template=template,
            fields={"due_date": "2026-01-24"},
            transcript="Test.",
            processed_at=processed_at,
            device="watch",
            duration_seconds=10.0,
        )

        # Without due_date should have fewer blocks
        assert len(content_without) < len(content_with)

        # Check that Due Date heading exists in with version
        heading_texts = [
            b["heading_2"]["rich_text"][0]["text"]["content"]
            for b in content_with
            if b["type"] == "heading_2"
        ]
        assert "Due Date" in heading_texts

    def test_build_page_content_invalid_template_fallback(self):
        """Test fallback when template is invalid."""
        builder = ContentBuilder()
        processed_at = datetime(2026, 1, 20, 14, 30, 22)

        # Invalid Jinja2 syntax
        template = """{% for item in %}broken{% endfor %}"""

        content = builder.build_page_content(
            page_body_template=template,
            fields={},
            transcript="Test transcript.",
            processed_at=processed_at,
            device="watch",
            duration_seconds=10.0,
        )

        # Should produce fallback content
        assert len(content) > 0

        # Check that fallback has Summary and Raw Transcript
        heading_texts = [
            b["heading_2"]["rich_text"][0]["text"]["content"]
            for b in content
            if b["type"] == "heading_2"
        ]
        assert "Summary" in heading_texts
        assert "Raw Transcript" in heading_texts

    def test_transcript_truncation(self):
        """Test transcript truncation at 2000 chars."""
        builder = ContentBuilder()
        processed_at = datetime(2026, 1, 20, 14, 30, 22)

        long_text = "A" * 2500

        content = builder.build_basic_page_content(
            transcript=long_text,
            processed_at=processed_at,
            device="watch",
            duration_seconds=300.0,
        )

        # Find transcript block
        transcript_text = content[3]["paragraph"]["rich_text"][0]["text"]["content"]
        assert len(transcript_text) == MAX_TRANSCRIPT_LENGTH
        assert transcript_text.endswith(TRUNCATION_INDICATOR)

    def test_markdown_to_blocks_headings(self):
        """Test markdown heading parsing."""
        builder = ContentBuilder()

        markdown = """## First Heading
Some text here.

## Second Heading
More text."""

        blocks = builder._markdown_to_blocks(markdown)

        heading_texts = [
            b["heading_2"]["rich_text"][0]["text"]["content"]
            for b in blocks
            if b["type"] == "heading_2"
        ]

        assert "First Heading" in heading_texts
        assert "Second Heading" in heading_texts

    def test_markdown_to_blocks_divider(self):
        """Test markdown divider parsing."""
        builder = ContentBuilder()

        markdown = """Some text.

---

More text."""

        blocks = builder._markdown_to_blocks(markdown)

        dividers = [b for b in blocks if b["type"] == "divider"]
        assert len(dividers) == 1

    def test_markdown_to_blocks_italic(self):
        """Test markdown italic parsing."""
        builder = ContentBuilder()

        markdown = """*This is italic text*"""

        blocks = builder._markdown_to_blocks(markdown)

        # Should have italic annotation
        italic_blocks = [
            b for b in blocks
            if b["type"] == "paragraph" and
            b["paragraph"]["rich_text"][0].get("annotations", {}).get("italic")
        ]
        assert len(italic_blocks) == 1


# ============================================================================
# NotionService Integration Tests
# ============================================================================

class TestNotionServiceEnhanced:
    """Tests for enhanced NotionService with template support."""

    @pytest.mark.asyncio
    async def test_create_template_page_task(
        self,
        task_template,
        task_classification,
        sample_transcription,
        sample_metadata,
        notion_success_response,
    ):
        """Test creating a template-specific task page."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.pages.create = AsyncMock(return_value=notion_success_response)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            result = await service.create_capture_page(
                transcription=sample_transcription,
                metadata=sample_metadata,
                classification=task_classification,
                template=task_template,
            )

            assert isinstance(result, NotionPage)
            assert result.id == notion_success_response["id"]

            # Verify API was called with correct properties
            call_kwargs = mock_client.pages.create.call_args[1]
            properties = call_kwargs["properties"]

            # Check template-specific properties
            assert "Task" in properties  # Title mapped to Task
            assert properties["Task"]["title"][0]["text"]["content"] == "Review quarterly report by Friday"
            assert "Priority" in properties
            assert properties["Priority"]["select"]["name"] == "High"
            assert "Type" in properties
            assert properties["Type"]["select"]["name"] == "Task"
            assert "Device" in properties
            assert properties["Device"]["select"]["name"] == "Watch"
            assert "Tags" in properties
            assert len(properties["Tags"]["multi_select"]) == 3

    @pytest.mark.asyncio
    async def test_create_template_page_uses_classification_title(
        self,
        task_template,
        task_classification,
        sample_transcription,
        sample_metadata,
        notion_success_response,
    ):
        """Test that classification title is used when no override."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.pages.create = AsyncMock(return_value=notion_success_response)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            await service.create_capture_page(
                transcription=sample_transcription,
                metadata=sample_metadata,
                classification=task_classification,
                template=task_template,
            )

            call_kwargs = mock_client.pages.create.call_args[1]
            title_content = call_kwargs["properties"]["Task"]["title"][0]["text"]["content"]
            assert title_content == task_classification.title

    @pytest.mark.asyncio
    async def test_create_template_page_title_override(
        self,
        task_template,
        task_classification,
        sample_transcription,
        sample_metadata,
        notion_success_response,
    ):
        """Test that title override is respected."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.pages.create = AsyncMock(return_value=notion_success_response)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            await service.create_capture_page(
                transcription=sample_transcription,
                metadata=sample_metadata,
                classification=task_classification,
                template=task_template,
                title="Custom Override Title",
            )

            call_kwargs = mock_client.pages.create.call_args[1]
            title_content = call_kwargs["properties"]["Task"]["title"][0]["text"]["content"]
            assert title_content == "Custom Override Title"

    @pytest.mark.asyncio
    async def test_create_template_page_content_rendered(
        self,
        task_template,
        task_classification,
        sample_transcription,
        sample_metadata,
        notion_success_response,
    ):
        """Test that page content is rendered from Jinja2 template."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.pages.create = AsyncMock(return_value=notion_success_response)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            await service.create_capture_page(
                transcription=sample_transcription,
                metadata=sample_metadata,
                classification=task_classification,
                template=task_template,
            )

            call_kwargs = mock_client.pages.create.call_args[1]
            children = call_kwargs["children"]

            # Should have content blocks
            assert len(children) > 0

            # Check for expected sections
            heading_texts = [
                block["heading_2"]["rich_text"][0]["text"]["content"]
                for block in children
                if block["type"] == "heading_2"
            ]
            assert "Context" in heading_texts
            assert "Raw Transcript" in heading_texts

    @pytest.mark.asyncio
    async def test_fallback_to_basic_page_without_template(
        self,
        sample_transcription,
        sample_metadata,
        notion_success_response,
    ):
        """Test fallback to basic page when no classification/template provided."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.pages.create = AsyncMock(return_value=notion_success_response)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            # Call without classification and template
            result = await service.create_capture_page(
                transcription=sample_transcription,
                metadata=sample_metadata,
            )

            assert isinstance(result, NotionPage)

            # Verify basic page was created
            call_kwargs = mock_client.pages.create.call_args[1]
            properties = call_kwargs["properties"]

            assert "Title" in properties
            assert "Type" in properties
            assert properties["Type"]["select"]["name"] == "General"

    @pytest.mark.asyncio
    async def test_template_page_applies_defaults(
        self,
        task_template,
        sample_transcription,
        sample_metadata,
        notion_success_response,
    ):
        """Test that default values are applied for missing fields."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.pages.create = AsyncMock(return_value=notion_success_response)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            # Classification with minimal fields
            minimal_classification = ClassificationResult(
                template_name="task",
                confidence=0.8,
                fields={"title": "My Task"},  # Only title, missing priority/status
                title="My Task",
                tags=[],
            )

            await service.create_capture_page(
                transcription=sample_transcription,
                metadata=sample_metadata,
                classification=minimal_classification,
                template=task_template,
            )

            call_kwargs = mock_client.pages.create.call_args[1]
            properties = call_kwargs["properties"]

            # Check defaults were applied
            assert "Priority" in properties
            assert properties["Priority"]["select"]["name"] == "Medium"  # default
            assert "Status" in properties
            assert properties["Status"]["select"]["name"] == "Not Started"  # default

    @pytest.mark.asyncio
    async def test_template_page_tags_from_classification(
        self,
        journal_template,
        sample_transcription,
        sample_metadata,
        notion_success_response,
    ):
        """Test that tags from classification are used."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.pages.create = AsyncMock(return_value=notion_success_response)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            classification = ClassificationResult(
                template_name="journal",
                confidence=0.9,
                fields={
                    "title": "2026-01-20 - Productive Day",
                    "date": "2026-01-20",
                    "mood": "Focused",
                    "summary": "Had a productive day.",
                },
                title="2026-01-20 - Productive Day",
                tags=["work", "productivity", "wins"],
            )

            await service.create_capture_page(
                transcription=sample_transcription,
                metadata=sample_metadata,
                classification=classification,
                template=journal_template,
            )

            call_kwargs = mock_client.pages.create.call_args[1]
            properties = call_kwargs["properties"]

            assert "Tags" in properties
            tag_names = [t["name"] for t in properties["Tags"]["multi_select"]]
            assert "work" in tag_names
            assert "productivity" in tag_names
            assert "wins" in tag_names
