"""Tests for synthesis generator and notion writer modules.

Tests cover:
- Synthesis generation with Claude API
- JSON response parsing
- Sparse week handling
- Summary page creation in Notion
- Error handling and retries
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.synthesis.generator import (
    SynthesisGenerator,
    SynthesisGenerationError,
    SynthesisParseError,
    SynthesisResult,
    generate_synthesis,
)
from src.synthesis.notion_writer import (
    NotionSummaryWriter,
    NotionWriterError,
    NotionWriterRateLimitError,
    SummaryPage,
    create_summary_page,
)
from src.synthesis.notion_query import VoiceCapture
from src.synthesis.prompt_builder import (
    CaptureStatistics,
    IdeaReference,
    WeeklySummaryData,
)


# --- Test Fixtures ---


@pytest.fixture
def sample_captures() -> List[VoiceCapture]:
    """Create sample captures for testing."""
    now = datetime.now()
    return [
        VoiceCapture(
            id="capture-1",
            url="https://notion.so/capture1",
            title="Task: Review quarterly report",
            captured_at=now - timedelta(days=2),
            template_type="Task",
            device="Watch",
            tags=["work", "quarterly"],
            content="Need to review the quarterly report by Friday.",
            properties={"Duration": {"type": "number", "number": 30}},
        ),
        VoiceCapture(
            id="capture-2",
            url="https://notion.so/capture2",
            title="Journal: Productive morning",
            captured_at=now - timedelta(days=1),
            template_type="Journal",
            device="Phone",
            tags=["reflection"],
            content="Had a productive morning working on the project.",
            properties={"Duration": {"type": "number", "number": 45}},
        ),
        VoiceCapture(
            id="capture-3",
            url="https://notion.so/capture3",
            title="Idea: Automate reporting",
            captured_at=now,
            template_type="Idea",
            device="Watch",
            tags=["automation", "idea"],
            content="What if we could automate the monthly reporting?",
            properties={"Duration": {"type": "number", "number": 60}},
        ),
    ]


@pytest.fixture
def sample_claude_response() -> Dict[str, Any]:
    """Create sample Claude API response."""
    return {
        "overview": "This week focused on quarterly planning and process improvements.",
        "accomplishments": [
            "Completed quarterly report review",
            "Identified automation opportunities",
        ],
        "key_activities": "Spent time reviewing quarterly metrics and brainstorming process improvements.",
        "challenges": [
            "Time constraints on report deadline",
        ],
        "ideas": [
            {
                "title": "Automate reporting",
                "url": "https://notion.so/capture3",
                "summary": "Automate monthly reporting process",
            }
        ],
        "insights": "Automation could save significant time in recurring tasks.",
        "upcoming": [
            "Finalize quarterly report",
            "Prototype automation solution",
        ],
    }


@pytest.fixture
def sample_synthesis_result(sample_captures) -> SynthesisResult:
    """Create sample synthesis result for testing."""
    now = datetime.now()
    start_date = now - timedelta(days=7)
    end_date = now

    summary_data = WeeklySummaryData(
        start_date=start_date.strftime("%B %d, %Y"),
        end_date=end_date.strftime("%B %d, %Y"),
        overview="Test week overview.",
        accomplishments=["First accomplishment", "Second accomplishment"],
        key_activities="Key activities narrative.",
        challenges=["A challenge"],
        ideas=[IdeaReference(title="Test Idea", url="https://notion.so/idea1", summary="Idea summary")],
        insights="Insights and reflections.",
        upcoming=["Upcoming item 1", "Upcoming item 2"],
        stats=CaptureStatistics(
            total_captures=3,
            by_type={"Task": 1, "Journal": 1, "Idea": 1},
            total_duration_seconds=135,
            supplemental_input_used=False,
        ),
    )

    return SynthesisResult(
        summary_data=summary_data,
        raw_response={"overview": "Test"},
        summary_markdown="# Week of Test\n\n## Overview\nTest overview.",
        start_date=start_date,
        end_date=end_date,
        capture_count=3,
        supplemental_input_used=False,
    )


# --- SynthesisGenerator Tests ---


class TestSynthesisGenerator:
    """Tests for SynthesisGenerator class."""

    def test_init(self):
        """Test generator initialization."""
        generator = SynthesisGenerator(api_key="test-key")
        assert generator._model == SynthesisGenerator.DEFAULT_MODEL
        assert generator._max_tokens == SynthesisGenerator.DEFAULT_MAX_TOKENS
        assert generator._max_retries == 3

    def test_init_custom_params(self):
        """Test generator with custom parameters."""
        generator = SynthesisGenerator(
            api_key="test-key",
            model="claude-3-opus-20240229",
            max_tokens=8192,
            max_retries=5,
        )
        assert generator._model == "claude-3-opus-20240229"
        assert generator._max_tokens == 8192
        assert generator._max_retries == 5

    @patch.object(SynthesisGenerator, '_call_claude_api')
    def test_generate_synthesis(self, mock_call, sample_captures, sample_claude_response):
        """Test successful synthesis generation."""
        mock_call.return_value = sample_claude_response

        generator = SynthesisGenerator(api_key="test-key")
        now = datetime.now()
        start_date = now - timedelta(days=7)
        end_date = now

        result = generator.generate_synthesis(
            captures=sample_captures,
            start_date=start_date,
            end_date=end_date,
        )

        assert isinstance(result, SynthesisResult)
        assert result.capture_count == 3
        assert result.supplemental_input_used is False
        assert len(result.summary_data.accomplishments) == 2
        assert "quarterly" in result.summary_data.overview.lower()

    @patch.object(SynthesisGenerator, '_call_claude_api')
    def test_generate_synthesis_with_supplemental_input(self, mock_call, sample_captures, sample_claude_response):
        """Test synthesis generation with supplemental input."""
        mock_call.return_value = sample_claude_response

        generator = SynthesisGenerator(api_key="test-key")
        now = datetime.now()
        start_date = now - timedelta(days=7)
        end_date = now

        result = generator.generate_synthesis(
            captures=sample_captures,
            start_date=start_date,
            end_date=end_date,
            supplemental_input="Additional context about the week.",
        )

        assert result.supplemental_input_used is True

    def test_check_sparse_week_not_sparse(self, sample_captures):
        """Test sparse week detection with enough captures."""
        generator = SynthesisGenerator(api_key="test-key")
        result = generator.check_sparse_week(sample_captures)

        assert result.is_sparse is False
        assert result.capture_count == 3
        assert len(result.questions) == 0

    def test_check_sparse_week_sparse(self):
        """Test sparse week detection with few captures."""
        generator = SynthesisGenerator(api_key="test-key")
        captures = [
            VoiceCapture(
                id="capture-1",
                url="https://notion.so/capture1",
                title="Single capture",
                captured_at=datetime.now(),
                template_type="General",
                device="Watch",
            )
        ]

        result = generator.check_sparse_week(captures)

        assert result.is_sparse is True
        assert result.capture_count == 1
        assert len(result.questions) == 3  # Default sparse week questions

    def test_format_sparse_week_questions(self):
        """Test formatting sparse week questions."""
        generator = SynthesisGenerator(api_key="test-key")
        captures = [
            VoiceCapture(
                id="capture-1",
                url="https://notion.so/capture1",
                title="Single capture",
                captured_at=datetime.now(),
                template_type="General",
                device="Watch",
            )
        ]

        result = generator.check_sparse_week(captures)
        formatted = generator.format_sparse_week_questions(result)

        assert "1 capture" in formatted
        assert "What were your main work focuses" in formatted
        assert "significant meetings" in formatted

    def test_process_sparse_week_response(self):
        """Test processing sparse week response."""
        generator = SynthesisGenerator(api_key="test-key")
        captures = [
            VoiceCapture(
                id="capture-1",
                url="https://notion.so/capture1",
                title="Single capture",
                captured_at=datetime.now(),
                template_type="General",
                device="Watch",
            )
        ]

        result = generator.check_sparse_week(captures)
        supplemental = generator.process_sparse_week_response(
            result=result,
            response="I focused on client meetings and project planning.",
        )

        assert "client meetings" in supplemental
        assert "project planning" in supplemental


class TestSynthesisGeneratorJsonParsing:
    """Tests for JSON parsing in SynthesisGenerator."""

    def test_extract_json_clean(self):
        """Test extracting clean JSON."""
        generator = SynthesisGenerator(api_key="test-key")
        json_str = '{"overview": "Test", "accomplishments": []}'

        result = generator._extract_json(json_str)

        assert result["overview"] == "Test"
        assert result["accomplishments"] == []

    def test_extract_json_from_code_block(self):
        """Test extracting JSON from markdown code block."""
        generator = SynthesisGenerator(api_key="test-key")
        response = '''Here is the synthesis:

```json
{"overview": "Test overview", "accomplishments": ["Item 1"]}
```

Let me know if you need changes.'''

        result = generator._extract_json(response)

        assert result["overview"] == "Test overview"
        assert result["accomplishments"] == ["Item 1"]

    def test_extract_json_from_generic_code_block(self):
        """Test extracting JSON from generic code block."""
        generator = SynthesisGenerator(api_key="test-key")
        response = '''```
{"overview": "Test", "accomplishments": []}
```'''

        result = generator._extract_json(response)

        assert result["overview"] == "Test"

    def test_extract_json_embedded(self):
        """Test extracting embedded JSON from text."""
        generator = SynthesisGenerator(api_key="test-key")
        response = 'Here is the result: {"overview": "Test", "accomplishments": []} Done.'

        result = generator._extract_json(response)

        assert result["overview"] == "Test"

    def test_extract_json_invalid(self):
        """Test handling invalid JSON."""
        generator = SynthesisGenerator(api_key="test-key")

        with pytest.raises(SynthesisParseError):
            generator._extract_json("This is not JSON at all")

    def test_extract_json_malformed(self):
        """Test handling malformed JSON."""
        generator = SynthesisGenerator(api_key="test-key")

        with pytest.raises(SynthesisParseError):
            generator._extract_json('{"overview": "Test", "accomplishments": [}')


class TestSynthesisGeneratorResponseParsing:
    """Tests for response parsing in SynthesisGenerator."""

    def test_parse_response_complete(self, sample_captures, sample_claude_response):
        """Test parsing complete response."""
        generator = SynthesisGenerator(api_key="test-key")
        now = datetime.now()

        result = generator._parse_response(
            response=sample_claude_response,
            captures=sample_captures,
            start_date=now - timedelta(days=7),
            end_date=now,
        )

        assert isinstance(result, WeeklySummaryData)
        assert result.overview == sample_claude_response["overview"]
        assert len(result.accomplishments) == 2
        assert len(result.ideas) == 1
        assert result.ideas[0].title == "Automate reporting"

    def test_parse_response_minimal(self, sample_captures):
        """Test parsing response with minimal fields."""
        generator = SynthesisGenerator(api_key="test-key")
        now = datetime.now()

        result = generator._parse_response(
            response={"overview": "Minimal week"},
            captures=sample_captures,
            start_date=now - timedelta(days=7),
            end_date=now,
        )

        assert result.overview == "Minimal week"
        assert result.accomplishments == []
        assert result.challenges == []

    def test_parse_response_with_supplemental(self, sample_captures, sample_claude_response):
        """Test parsing response with supplemental input."""
        generator = SynthesisGenerator(api_key="test-key")
        now = datetime.now()

        result = generator._parse_response(
            response=sample_claude_response,
            captures=sample_captures,
            start_date=now - timedelta(days=7),
            end_date=now,
            supplemental_input="Extra context",
        )

        assert result.stats.supplemental_input_used is True


# --- NotionSummaryWriter Tests ---


class TestNotionSummaryWriter:
    """Tests for NotionSummaryWriter class."""

    def test_init(self):
        """Test writer initialization."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )
        assert writer._database_id == "test-db-id"
        assert writer._max_retries == 3

    def test_build_properties(self, sample_synthesis_result):
        """Test building Notion properties."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        properties = writer._build_properties(
            title="Week of January 13, 2026 - January 20, 2026",
            start_date=sample_synthesis_result.start_date,
            end_date=sample_synthesis_result.end_date,
            capture_count=3,
            supplemental_input_used=False,
        )

        assert "Title" in properties
        assert properties["Title"]["title"][0]["text"]["content"].startswith("Week of")
        assert "Date Range" in properties
        assert "Captures" in properties
        assert properties["Captures"]["number"] == 3

    def test_build_properties_with_supplemental(self, sample_synthesis_result):
        """Test building properties with supplemental input flag."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        properties = writer._build_properties(
            title="Test Week",
            start_date=sample_synthesis_result.start_date,
            end_date=sample_synthesis_result.end_date,
            capture_count=3,
            supplemental_input_used=True,
        )

        assert "Supplemental Input" in properties
        assert properties["Supplemental Input"]["checkbox"] is True

    def test_build_page_content(self, sample_synthesis_result, sample_captures):
        """Test building page content blocks."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        blocks = writer._build_page_content(
            summary_data=sample_synthesis_result.summary_data,
            source_captures=sample_captures,
        )

        assert len(blocks) > 0

        # Check for required sections
        headings = [
            block["heading_2"]["rich_text"][0]["text"]["content"]
            for block in blocks
            if block.get("type") == "heading_2"
        ]

        assert "Overview" in headings
        assert "Accomplishments" in headings
        assert "Key Activities" in headings
        assert "Challenges & Blockers" in headings
        assert "Ideas Generated" in headings
        assert "Insights & Reflections" in headings
        assert "Upcoming / Next Week" in headings
        assert "Capture Statistics" in headings
        assert "Source Captures" in headings

    def test_build_page_content_without_source_captures(self, sample_synthesis_result):
        """Test building page content without source captures."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        blocks = writer._build_page_content(
            summary_data=sample_synthesis_result.summary_data,
            source_captures=None,
        )

        headings = [
            block["heading_2"]["rich_text"][0]["text"]["content"]
            for block in blocks
            if block.get("type") == "heading_2"
        ]

        # Source Captures section should not be present
        assert "Source Captures" not in headings

    def test_heading_block(self):
        """Test creating heading block."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        block = writer._heading_block("Test Heading")

        assert block["type"] == "heading_2"
        assert block["heading_2"]["rich_text"][0]["text"]["content"] == "Test Heading"

    def test_paragraph_block(self):
        """Test creating paragraph block."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        block = writer._paragraph_block("Test paragraph content")

        assert block["type"] == "paragraph"
        assert block["paragraph"]["rich_text"][0]["text"]["content"] == "Test paragraph content"

    def test_paragraph_block_long_text(self):
        """Test creating paragraph block with long text (>2000 chars)."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        long_text = "A" * 5000
        block = writer._paragraph_block(long_text)

        # Should be split into multiple rich_text elements
        assert len(block["paragraph"]["rich_text"]) == 3  # 2000 + 2000 + 1000

    def test_bulleted_list_block(self):
        """Test creating bulleted list block."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        block = writer._bulleted_list_block("List item")

        assert block["type"] == "bulleted_list_item"
        assert block["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "List item"

    def test_idea_block_with_url(self):
        """Test creating idea block with link."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        idea = IdeaReference(
            title="Test Idea",
            url="https://notion.so/test",
            summary="Idea summary",
        )
        block = writer._idea_block(idea)

        assert block["type"] == "bulleted_list_item"
        rich_text = block["bulleted_list_item"]["rich_text"]
        assert rich_text[0]["text"]["link"]["url"] == "https://notion.so/test"
        assert rich_text[1]["text"]["content"] == ": Idea summary"

    def test_idea_block_without_url(self):
        """Test creating idea block without link."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        idea = IdeaReference(
            title="Test Idea",
            url="",
            summary="",
        )
        block = writer._idea_block(idea)

        assert block["type"] == "bulleted_list_item"
        rich_text = block["bulleted_list_item"]["rich_text"]
        assert "link" not in rich_text[0]["text"]

    def test_capture_link_block(self, sample_captures):
        """Test creating capture link block."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        block = writer._capture_link_block(sample_captures[0])

        assert block["type"] == "bulleted_list_item"
        rich_text = block["bulleted_list_item"]["rich_text"]
        assert "[Task]" in rich_text[0]["text"]["content"]
        assert rich_text[1]["text"]["link"]["url"] == "https://notion.so/capture1"


class TestNotionSummaryWriterRetry:
    """Tests for retry logic in NotionSummaryWriter."""

    def test_calculate_backoff(self):
        """Test backoff calculation."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
            base_backoff=5.0,
            max_backoff=300.0,
        )

        # First attempt: 5.0 + jitter
        backoff0 = writer._calculate_backoff(0)
        assert 5.0 <= backoff0 <= 5.5

        # Second attempt: 10.0 + jitter
        backoff1 = writer._calculate_backoff(1)
        assert 10.0 <= backoff1 <= 11.0

        # Third attempt: 20.0 + jitter
        backoff2 = writer._calculate_backoff(2)
        assert 20.0 <= backoff2 <= 22.0

        # Should cap at max_backoff
        backoff10 = writer._calculate_backoff(10)
        assert backoff10 <= 330.0  # max_backoff + 10% jitter


@pytest.mark.asyncio
class TestNotionSummaryWriterAsync:
    """Async tests for NotionSummaryWriter."""

    async def test_create_summary_page(self, sample_synthesis_result, sample_captures):
        """Test creating summary page."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        # Mock the client
        mock_response = {
            "id": "page-123",
            "url": "https://notion.so/page123",
        }
        writer._client.pages.create = AsyncMock(return_value=mock_response)

        result = await writer.create_summary_page(
            synthesis_result=sample_synthesis_result,
            source_captures=sample_captures,
        )

        assert isinstance(result, SummaryPage)
        assert result.id == "page-123"
        assert result.url == "https://notion.so/page123"
        assert "Week of" in result.title

        # Verify create was called with correct params
        writer._client.pages.create.assert_called_once()
        call_kwargs = writer._client.pages.create.call_args[1]
        assert call_kwargs["parent"]["database_id"] == "test-db-id"
        assert "Title" in call_kwargs["properties"]

    async def test_create_summary_page_without_source_captures(self, sample_synthesis_result):
        """Test creating summary page without source captures."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        mock_response = {
            "id": "page-456",
            "url": "https://notion.so/page456",
        }
        writer._client.pages.create = AsyncMock(return_value=mock_response)

        result = await writer.create_summary_page(
            synthesis_result=sample_synthesis_result,
            source_captures=None,
        )

        assert result.id == "page-456"

    async def test_close(self):
        """Test closing the writer."""
        writer = NotionSummaryWriter(
            api_key="test-key",
            database_id="test-db-id",
        )

        writer._client.aclose = AsyncMock()
        await writer.close()
        writer._client.aclose.assert_called_once()


# --- Convenience Function Tests ---


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @patch.object(SynthesisGenerator, '_call_claude_api')
    def test_generate_synthesis_function(self, mock_call, sample_captures, sample_claude_response):
        """Test generate_synthesis convenience function."""
        mock_call.return_value = sample_claude_response

        now = datetime.now()
        result = generate_synthesis(
            api_key="test-key",
            captures=sample_captures,
            start_date=now - timedelta(days=7),
            end_date=now,
        )

        assert isinstance(result, SynthesisResult)
        assert result.capture_count == 3


@pytest.mark.asyncio
class TestAsyncConvenienceFunctions:
    """Tests for async convenience functions."""

    async def test_create_summary_page_function(self, sample_synthesis_result):
        """Test create_summary_page convenience function."""
        with patch.object(NotionSummaryWriter, '_create_page_with_retry') as mock_create:
            mock_create.return_value = {
                "id": "page-789",
                "url": "https://notion.so/page789",
            }

            result = await create_summary_page(
                api_key="test-key",
                database_id="test-db-id",
                synthesis_result=sample_synthesis_result,
            )

            assert result.id == "page-789"


# --- Integration-style Tests ---


class TestSynthesisIntegration:
    """Integration-style tests for synthesis flow."""

    @patch.object(SynthesisGenerator, '_call_claude_api')
    def test_full_synthesis_flow(self, mock_call, sample_captures, sample_claude_response):
        """Test full synthesis flow from captures to result."""
        mock_call.return_value = sample_claude_response

        generator = SynthesisGenerator(api_key="test-key")
        now = datetime.now()
        start_date = now - timedelta(days=7)
        end_date = now

        # Step 1: Check for sparse week
        sparse_result = generator.check_sparse_week(sample_captures)
        assert sparse_result.is_sparse is False

        # Step 2: Generate synthesis
        result = generator.generate_synthesis(
            captures=sample_captures,
            start_date=start_date,
            end_date=end_date,
        )

        # Step 3: Verify result
        assert result.capture_count == 3
        assert len(result.summary_data.accomplishments) > 0
        assert result.summary_markdown is not None
        assert len(result.summary_markdown) > 0

    @patch.object(SynthesisGenerator, '_call_claude_api')
    def test_sparse_week_flow(self, mock_call, sample_claude_response):
        """Test sparse week handling flow."""
        mock_call.return_value = sample_claude_response

        generator = SynthesisGenerator(api_key="test-key")
        now = datetime.now()

        # Create sparse captures
        sparse_captures = [
            VoiceCapture(
                id="capture-1",
                url="https://notion.so/capture1",
                title="Single capture",
                captured_at=now,
                template_type="General",
                device="Watch",
            )
        ]

        # Step 1: Detect sparse week
        sparse_result = generator.check_sparse_week(sparse_captures)
        assert sparse_result.is_sparse is True

        # Step 2: Get questions
        questions = generator.format_sparse_week_questions(sparse_result)
        assert "1 capture" in questions

        # Step 3: Process response
        supplemental = generator.process_sparse_week_response(
            sparse_result,
            "I had several client meetings and worked on the roadmap.",
        )
        assert "client meetings" in supplemental

        # Step 4: Generate with supplemental
        result = generator.generate_synthesis(
            captures=sparse_captures,
            start_date=now - timedelta(days=7),
            end_date=now,
            supplemental_input=supplemental,
        )

        assert result.supplemental_input_used is True
