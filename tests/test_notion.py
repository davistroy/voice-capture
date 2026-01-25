"""Tests for Notion integration service.

Tests cover:
- NotionService page creation with mocked client
- PageBuilder property and content generation
- Retry logic with exponential backoff
- Rate limiting (HTTP 429) handling
- Transcript truncation
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from notion_client.errors import HTTPResponseError

from src.notion.client import (
    NotionService,
    NotionPage,
    NotionError,
    NotionRateLimitError,
    CaptureMetadata,
)
from src.notion.page_builder import PageBuilder, MAX_TRANSCRIPT_LENGTH, TRUNCATION_INDICATOR
from src.models.transcription import TranscriptionResult


# Fixture paths
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
def notion_rate_limit_response():
    """Load Notion rate limit response."""
    return load_fixture("notion_rate_limit.json")


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
def long_transcription():
    """Create a transcription that exceeds the truncation limit."""
    # Create text that's definitely over 2000 chars
    long_text = "This is a long recording. " * 100  # ~2600 chars
    return TranscriptionResult(
        text=long_text,
        duration_seconds=180.0,
        language="en",
        segments=None,
    )


@pytest.fixture
def sample_metadata():
    """Create sample capture metadata."""
    return CaptureMetadata(
        captured_at=datetime(2026, 1, 20, 14, 30, 22),
        device="watch",
        duration_seconds=15.5,
    )


# ============================================================================
# PageBuilder Tests
# ============================================================================

class TestPageBuilder:
    """Tests for PageBuilder class."""

    def test_build_properties_basic(self):
        """Test building basic properties for generic template."""
        builder = PageBuilder()
        captured_at = datetime(2026, 1, 20, 14, 30, 22)

        props = builder.build_properties(
            title="Test capture title",
            captured_at=captured_at,
            device="watch",
            template_type="General",
            tags=[],
        )

        # Check Title
        assert props["Title"]["title"][0]["text"]["content"] == "Test capture title"

        # Check Date
        assert props["Date"]["date"]["start"] == captured_at.isoformat()

        # Check Device (should be capitalized)
        assert props["Device"]["rich_text"][0]["text"]["content"] == "Watch"

        # Check Type
        assert props["Type"]["select"]["name"] == "General"

        # Check Tags (empty)
        assert props["Tags"]["multi_select"] == []

    def test_build_properties_with_tags(self):
        """Test building properties with tags."""
        builder = PageBuilder()
        captured_at = datetime(2026, 1, 20, 14, 30, 22)

        props = builder.build_properties(
            title="Tagged capture",
            captured_at=captured_at,
            device="phone",
            template_type="Task",
            tags=["work", "urgent"],
        )

        # Check Tags
        assert len(props["Tags"]["multi_select"]) == 2
        assert props["Tags"]["multi_select"][0]["name"] == "work"
        assert props["Tags"]["multi_select"][1]["name"] == "urgent"

    def test_build_properties_device_formatting(self):
        """Test device name formatting (lowercase to title case)."""
        builder = PageBuilder()
        captured_at = datetime(2026, 1, 20, 14, 30, 22)

        # Test watch
        props = builder.build_properties(
            title="Test", captured_at=captured_at, device="watch"
        )
        assert props["Device"]["rich_text"][0]["text"]["content"] == "Watch"

        # Test phone
        props = builder.build_properties(
            title="Test", captured_at=captured_at, device="phone"
        )
        assert props["Device"]["rich_text"][0]["text"]["content"] == "Phone"

        # Test unknown
        props = builder.build_properties(
            title="Test", captured_at=captured_at, device="unknown"
        )
        assert props["Device"]["rich_text"][0]["text"]["content"] == "Unknown"

        # Test uppercase input
        props = builder.build_properties(
            title="Test", captured_at=captured_at, device="WATCH"
        )
        assert props["Device"]["rich_text"][0]["text"]["content"] == "Watch"

    def test_build_page_content_structure(self):
        """Test page content has correct structure."""
        builder = PageBuilder()
        captured_at = datetime(2026, 1, 20, 14, 30, 22)

        content = builder.build_page_content(
            transcript="Test transcript text.",
            captured_at=captured_at,
            device="watch",
            duration_seconds=10.5,
        )

        # Should have: Summary heading, summary text, Raw Transcript heading,
        # transcript text, divider, metadata footer
        assert len(content) == 6

        # Check Summary heading
        assert content[0]["type"] == "heading_2"
        assert content[0]["heading_2"]["rich_text"][0]["text"]["content"] == "Summary"

        # Check Summary paragraph
        assert content[1]["type"] == "paragraph"

        # Check Raw Transcript heading
        assert content[2]["type"] == "heading_2"
        assert content[2]["heading_2"]["rich_text"][0]["text"]["content"] == "Raw Transcript"

        # Check transcript paragraph
        assert content[3]["type"] == "paragraph"
        assert "Test transcript text" in content[3]["paragraph"]["rich_text"][0]["text"]["content"]

        # Check divider
        assert content[4]["type"] == "divider"

        # Check metadata footer (italic)
        assert content[5]["type"] == "paragraph"
        footer_text = content[5]["paragraph"]["rich_text"][0]["text"]["content"]
        assert "2026-01-20" in footer_text
        assert "Watch" in footer_text
        assert "10.5s" in footer_text
        assert content[5]["paragraph"]["rich_text"][0]["annotations"]["italic"] is True

    def test_build_page_content_with_custom_summary(self):
        """Test page content with custom summary."""
        builder = PageBuilder()
        captured_at = datetime(2026, 1, 20, 14, 30, 22)

        content = builder.build_page_content(
            transcript="Full transcript here.",
            captured_at=captured_at,
            device="phone",
            duration_seconds=20.0,
            summary="Custom summary text.",
        )

        # Check that custom summary is used
        summary_text = content[1]["paragraph"]["rich_text"][0]["text"]["content"]
        assert summary_text == "Custom summary text."

    def test_transcript_truncation(self):
        """Test transcript truncation at 2000 chars."""
        builder = PageBuilder()
        captured_at = datetime(2026, 1, 20, 14, 30, 22)

        # Create long transcript
        long_text = "A" * 2500

        content = builder.build_page_content(
            transcript=long_text,
            captured_at=captured_at,
            device="watch",
            duration_seconds=300.0,
        )

        # Check transcript is truncated
        transcript_text = content[3]["paragraph"]["rich_text"][0]["text"]["content"]
        assert len(transcript_text) == MAX_TRANSCRIPT_LENGTH
        assert transcript_text.endswith(TRUNCATION_INDICATOR)

    def test_transcript_no_truncation_when_short(self):
        """Test transcript is not truncated when under limit."""
        builder = PageBuilder()
        captured_at = datetime(2026, 1, 20, 14, 30, 22)

        short_text = "Short transcript."

        content = builder.build_page_content(
            transcript=short_text,
            captured_at=captured_at,
            device="watch",
            duration_seconds=5.0,
        )

        transcript_text = content[3]["paragraph"]["rich_text"][0]["text"]["content"]
        assert transcript_text == short_text
        assert TRUNCATION_INDICATOR not in transcript_text

    def test_extract_summary_multiple_sentences(self):
        """Test summary extraction from multi-sentence text."""
        builder = PageBuilder()

        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        summary = builder._extract_summary(text, max_sentences=3)

        assert "First sentence." in summary
        assert "Second sentence." in summary
        assert "Third sentence." in summary
        assert "Fourth sentence." not in summary

    def test_extract_summary_exclamation_and_question(self):
        """Test summary handles different sentence endings."""
        builder = PageBuilder()

        text = "Wow! Is this working? Yes it is."
        summary = builder._extract_summary(text, max_sentences=3)

        assert "Wow!" in summary
        assert "Is this working?" in summary
        assert "Yes it is." in summary

    def test_extract_summary_empty_text(self):
        """Test summary with empty text."""
        builder = PageBuilder()

        summary = builder._extract_summary("")
        assert summary == "No transcript content."

    def test_format_device_name(self):
        """Test device name formatting."""
        builder = PageBuilder()

        assert builder._format_device_name("watch") == "Watch"
        assert builder._format_device_name("WATCH") == "Watch"
        assert builder._format_device_name("phone") == "Phone"
        assert builder._format_device_name("PHONE") == "Phone"
        assert builder._format_device_name("unknown") == "Unknown"
        assert builder._format_device_name("other") == "Unknown"


# ============================================================================
# NotionService Tests
# ============================================================================

class TestNotionService:
    """Tests for NotionService class."""

    @pytest.mark.asyncio
    async def test_create_capture_page_success(
        self, sample_transcription, sample_metadata, notion_success_response
    ):
        """Test successful page creation."""
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
            )

            assert isinstance(result, NotionPage)
            assert result.id == notion_success_response["id"]
            assert result.url == notion_success_response["url"]

            # Verify API was called with correct structure
            mock_client.pages.create.assert_called_once()
            call_kwargs = mock_client.pages.create.call_args[1]

            assert call_kwargs["parent"]["database_id"] == "test-db-id"
            assert "Title" in call_kwargs["properties"]
            assert "Date" in call_kwargs["properties"]
            assert "Device" in call_kwargs["properties"]
            assert "Type" in call_kwargs["properties"]

    @pytest.mark.asyncio
    async def test_create_capture_page_custom_title(
        self, sample_transcription, sample_metadata, notion_success_response
    ):
        """Test page creation with custom title."""
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
                title="Custom Title Here",
            )

            call_kwargs = mock_client.pages.create.call_args[1]
            title_content = call_kwargs["properties"]["Title"]["title"][0]["text"]["content"]
            assert title_content == "Custom Title Here"

    @pytest.mark.asyncio
    async def test_create_capture_page_auto_title_from_transcript(
        self, sample_transcription, sample_metadata, notion_success_response
    ):
        """Test page creation auto-generates title from transcript."""
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
            )

            call_kwargs = mock_client.pages.create.call_args[1]
            title_content = call_kwargs["properties"]["Title"]["title"][0]["text"]["content"]

            # Should be first sentence from transcription
            assert "review the quarterly report" in title_content.lower()

    @pytest.mark.asyncio
    async def test_retry_on_server_error(
        self, sample_transcription, sample_metadata, notion_success_response
    ):
        """Test retry logic on server error (5xx)."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()

            # Create a mock HTTP error for 500
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.headers = {}
            error_500 = HTTPResponseError(mock_response, "Server error")
            error_500.status = 500

            # First two calls fail, third succeeds
            mock_client.pages.create = AsyncMock(
                side_effect=[error_500, error_500, notion_success_response]
            )
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
                base_backoff=0.01,  # Fast backoff for testing
            )

            result = await service.create_capture_page(
                transcription=sample_transcription,
                metadata=sample_metadata,
            )

            assert isinstance(result, NotionPage)
            assert mock_client.pages.create.call_count == 3

    @pytest.mark.asyncio
    async def test_fail_after_max_retries(
        self, sample_transcription, sample_metadata
    ):
        """Test failure after max retries exhausted."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()

            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.headers = {}
            error_500 = HTTPResponseError(mock_response, "Server error")
            error_500.status = 500

            # All calls fail
            mock_client.pages.create = AsyncMock(side_effect=error_500)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
                max_retries=3,
                base_backoff=0.01,
            )

            with pytest.raises(NotionError) as exc_info:
                await service.create_capture_page(
                    transcription=sample_transcription,
                    metadata=sample_metadata,
                )

            assert "after 4 attempts" in str(exc_info.value)
            assert mock_client.pages.create.call_count == 4  # Initial + 3 retries

    @pytest.mark.asyncio
    async def test_rate_limit_handling(
        self, sample_transcription, sample_metadata, notion_success_response
    ):
        """Test rate limit (429) handling with retry."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()

            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.headers = {"Retry-After": "0.1"}
            error_429 = HTTPResponseError(mock_response, "Rate limited")
            error_429.status = 429
            error_429.response = mock_response

            # First call rate limited, second succeeds
            mock_client.pages.create = AsyncMock(
                side_effect=[error_429, notion_success_response]
            )
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            result = await service.create_capture_page(
                transcription=sample_transcription,
                metadata=sample_metadata,
            )

            assert isinstance(result, NotionPage)
            assert mock_client.pages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_error_after_max_retries(
        self, sample_transcription, sample_metadata
    ):
        """Test NotionRateLimitError raised after max retries on 429."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()

            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.headers = {"Retry-After": "0.01"}
            error_429 = HTTPResponseError(mock_response, "Rate limited")
            error_429.status = 429
            error_429.response = mock_response

            mock_client.pages.create = AsyncMock(side_effect=error_429)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
                max_retries=2,
            )

            with pytest.raises(NotionRateLimitError) as exc_info:
                await service.create_capture_page(
                    transcription=sample_transcription,
                    metadata=sample_metadata,
                )

            assert exc_info.value.retry_after > 0

    @pytest.mark.asyncio
    async def test_client_error_no_retry(
        self, sample_transcription, sample_metadata
    ):
        """Test client error (4xx except 429) fails immediately without retry."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()

            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.headers = {}
            error_400 = HTTPResponseError(mock_response, "Bad request")
            error_400.status = 400

            mock_client.pages.create = AsyncMock(side_effect=error_400)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            with pytest.raises(NotionError) as exc_info:
                await service.create_capture_page(
                    transcription=sample_transcription,
                    metadata=sample_metadata,
                )

            assert "Client error" in str(exc_info.value)
            # Should only be called once (no retries for client errors)
            assert mock_client.pages.create.call_count == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_calculation(self):
        """Test exponential backoff calculation."""
        service = NotionService(
            api_key="test-key",
            database_id="test-db-id",
            base_backoff=5.0,
            max_backoff=300.0,
        )

        # Attempt 0: ~5s + jitter
        backoff_0 = service._calculate_backoff(0)
        assert 5.0 <= backoff_0 <= 5.5  # Base + 10% jitter

        # Attempt 1: ~10s + jitter
        backoff_1 = service._calculate_backoff(1)
        assert 10.0 <= backoff_1 <= 11.0

        # Attempt 2: ~20s + jitter
        backoff_2 = service._calculate_backoff(2)
        assert 20.0 <= backoff_2 <= 22.0

        # Attempt 5: Should be capped at max_backoff
        backoff_5 = service._calculate_backoff(5)
        assert backoff_5 <= 330.0  # Max + 10% jitter

    def test_extract_retry_after_from_header(self):
        """Test extracting Retry-After header value."""
        service = NotionService(
            api_key="test-key",
            database_id="test-db-id",
        )

        mock_response = MagicMock()
        mock_response.headers = {"Retry-After": "5"}
        error = HTTPResponseError(mock_response, "Rate limited")
        error.response = mock_response

        retry_after = service._extract_retry_after(error)
        assert retry_after == 5.0

    def test_extract_retry_after_default(self):
        """Test default Retry-After when header not present."""
        service = NotionService(
            api_key="test-key",
            database_id="test-db-id",
        )

        mock_response = MagicMock()
        mock_response.headers = {}
        error = HTTPResponseError(mock_response, "Rate limited")
        error.response = mock_response

        retry_after = service._extract_retry_after(error)
        assert retry_after == 1.0


# ============================================================================
# Integration Tests (with mocked API)
# ============================================================================

class TestNotionIntegration:
    """Integration tests for Notion service with realistic scenarios."""

    @pytest.mark.asyncio
    async def test_full_capture_page_flow(
        self, sample_metadata, notion_success_response
    ):
        """Test complete flow from transcription to Notion page."""
        transcription = TranscriptionResult(
            text="Meeting notes from today. Discussed the quarterly goals. Need to follow up with marketing team.",
            duration_seconds=45.0,
            language="en",
        )

        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.pages.create = AsyncMock(return_value=notion_success_response)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            result = await service.create_capture_page(
                transcription=transcription,
                metadata=sample_metadata,
            )

            # Verify result
            assert result.id is not None
            assert result.url is not None
            assert "notion.so" in result.url

            # Verify page structure
            call_kwargs = mock_client.pages.create.call_args[1]

            # Check properties
            props = call_kwargs["properties"]
            assert props["Type"]["select"]["name"] == "General"
            assert props["Device"]["rich_text"][0]["text"]["content"] == "Watch"
            assert len(props["Tags"]["multi_select"]) == 0

            # Check content blocks
            children = call_kwargs["children"]
            assert len(children) == 6

            # Verify transcript is in content
            transcript_block = children[3]
            assert "Meeting notes from today" in transcript_block["paragraph"]["rich_text"][0]["text"]["content"]

    @pytest.mark.asyncio
    async def test_long_transcript_truncated(
        self, long_transcription, sample_metadata, notion_success_response
    ):
        """Test long transcript is truncated in Notion page."""
        with patch("src.notion.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.pages.create = AsyncMock(return_value=notion_success_response)
            mock_client_class.return_value = mock_client

            service = NotionService(
                api_key="test-key",
                database_id="test-db-id",
            )

            await service.create_capture_page(
                transcription=long_transcription,
                metadata=sample_metadata,
            )

            call_kwargs = mock_client.pages.create.call_args[1]
            children = call_kwargs["children"]

            # Find transcript block (index 3)
            transcript_text = children[3]["paragraph"]["rich_text"][0]["text"]["content"]

            assert len(transcript_text) == MAX_TRANSCRIPT_LENGTH
            assert transcript_text.endswith(TRUNCATION_INDICATOR)
