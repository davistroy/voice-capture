"""Tests for Notion query module for weekly synthesis.

Tests cover:
- NotionQueryService date range queries
- Pagination handling for large result sets
- group_by_template function
- Property extraction from Notion pages
- Page content fetching
- Retry logic and error handling
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from notion_client.errors import HTTPResponseError

from src.synthesis.notion_query import (
    NotionQueryService,
    NotionQueryError,
    NotionQueryRateLimitError,
    VoiceCapture,
    group_by_template,
    query_captures_by_date_range,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_notion_page():
    """Create a sample Notion page response."""
    return {
        "id": "page-123-abc",
        "url": "https://notion.so/page-123-abc",
        "properties": {
            "Title": {
                "type": "title",
                "title": [{"plain_text": "Review quarterly report"}]
            },
            "Date": {
                "type": "date",
                "date": {"start": "2026-01-20T14:30:00"}
            },
            "Type": {
                "type": "select",
                "select": {"name": "Task"}
            },
            "Device": {
                "type": "select",
                "select": {"name": "Watch"}
            },
            "Tags": {
                "type": "multi_select",
                "multi_select": [
                    {"name": "work"},
                    {"name": "quarterly-review"}
                ]
            }
        }
    }


@pytest.fixture
def sample_notion_page_journal():
    """Create a sample Journal page response."""
    return {
        "id": "page-456-def",
        "url": "https://notion.so/page-456-def",
        "properties": {
            "Title": {
                "type": "title",
                "title": [{"plain_text": "Productive day reflections"}]
            },
            "Date": {
                "type": "date",
                "date": {"start": "2026-01-21"}
            },
            "Type": {
                "type": "select",
                "select": {"name": "Journal"}
            },
            "Device": {
                "type": "select",
                "select": {"name": "Phone"}
            },
            "Tags": {
                "type": "multi_select",
                "multi_select": [{"name": "personal"}]
            }
        }
    }


@pytest.fixture
def sample_blocks_response():
    """Create a sample blocks response for page content."""
    return {
        "results": [
            {
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"plain_text": "Summary"}]
                }
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "This is the summary text."}]
                }
            },
            {
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"plain_text": "Raw Transcript"}]
                }
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "Full transcript content here."}]
                }
            }
        ],
        "has_more": False,
        "next_cursor": None
    }


@pytest.fixture
def sample_database_response(sample_notion_page, sample_notion_page_journal):
    """Create a sample database query response."""
    return {
        "results": [sample_notion_page, sample_notion_page_journal],
        "has_more": False,
        "next_cursor": None
    }


@pytest.fixture
def paginated_response_page1(sample_notion_page):
    """First page of paginated results."""
    return {
        "results": [sample_notion_page],
        "has_more": True,
        "next_cursor": "cursor-abc-123"
    }


@pytest.fixture
def paginated_response_page2(sample_notion_page_journal):
    """Second page of paginated results."""
    return {
        "results": [sample_notion_page_journal],
        "has_more": False,
        "next_cursor": None
    }


# ============================================================================
# VoiceCapture Tests
# ============================================================================

class TestVoiceCapture:
    """Tests for VoiceCapture dataclass."""

    def test_create_voice_capture(self):
        """Test creating a VoiceCapture instance."""
        capture = VoiceCapture(
            id="test-id",
            url="https://notion.so/test-id",
            title="Test capture",
            captured_at=datetime(2026, 1, 20, 14, 30),
            template_type="Task",
            device="Watch",
            tags=["work"],
            content="Test content",
        )

        assert capture.id == "test-id"
        assert capture.title == "Test capture"
        assert capture.template_type == "Task"
        assert capture.tags == ["work"]

    def test_voice_capture_defaults(self):
        """Test VoiceCapture default values."""
        capture = VoiceCapture(
            id="test-id",
            url="https://notion.so/test-id",
            title="Test",
            captured_at=None,
            template_type="General",
            device="Unknown",
        )

        assert capture.tags == []
        assert capture.content == ""
        assert capture.properties == {}


# ============================================================================
# NotionQueryService Tests
# ============================================================================

class TestNotionQueryService:
    """Tests for NotionQueryService class."""

    @pytest.mark.asyncio
    async def test_query_captures_by_date_range_success(
        self, sample_database_response, sample_blocks_response
    ):
        """Test successful date range query."""
        with patch("src.synthesis.notion_query.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.databases.query = AsyncMock(return_value=sample_database_response)
            mock_client.blocks.children.list = AsyncMock(return_value=sample_blocks_response)
            mock_client_class.return_value = mock_client

            service = NotionQueryService(
                api_key="test-key",
                database_id="test-db-id",
            )

            start_date = datetime(2026, 1, 15)
            end_date = datetime(2026, 1, 25)

            captures = await service.query_captures_by_date_range(
                start_date=start_date,
                end_date=end_date,
            )

            assert len(captures) == 2
            assert captures[0].title == "Review quarterly report"
            assert captures[0].template_type == "Task"
            assert captures[0].device == "Watch"
            assert captures[0].tags == ["work", "quarterly-review"]
            assert "Summary" in captures[0].content

            # Verify query was called with correct filter
            mock_client.databases.query.assert_called_once()
            call_kwargs = mock_client.databases.query.call_args[1]
            assert call_kwargs["database_id"] == "test-db-id"
            assert "filter" in call_kwargs

    @pytest.mark.asyncio
    async def test_query_captures_without_content(
        self, sample_database_response
    ):
        """Test query without fetching page content."""
        with patch("src.synthesis.notion_query.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.databases.query = AsyncMock(return_value=sample_database_response)
            mock_client_class.return_value = mock_client

            service = NotionQueryService(
                api_key="test-key",
                database_id="test-db-id",
            )

            captures = await service.query_captures_by_date_range(
                start_date=datetime(2026, 1, 15),
                end_date=datetime(2026, 1, 25),
                include_content=False,
            )

            assert len(captures) == 2
            # Content should be empty when not fetched
            assert captures[0].content == ""
            # blocks.children.list should not be called
            mock_client.blocks.children.list.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_last_n_days(self, sample_database_response, sample_blocks_response):
        """Test convenience method for last N days query."""
        with patch("src.synthesis.notion_query.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.databases.query = AsyncMock(return_value=sample_database_response)
            mock_client.blocks.children.list = AsyncMock(return_value=sample_blocks_response)
            mock_client_class.return_value = mock_client

            service = NotionQueryService(
                api_key="test-key",
                database_id="test-db-id",
            )

            captures = await service.query_last_n_days(days=7)

            assert len(captures) == 2
            mock_client.databases.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_pagination_handling(
        self, paginated_response_page1, paginated_response_page2, sample_blocks_response
    ):
        """Test handling of paginated results."""
        with patch("src.synthesis.notion_query.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            # Return paginated responses
            mock_client.databases.query = AsyncMock(
                side_effect=[paginated_response_page1, paginated_response_page2]
            )
            mock_client.blocks.children.list = AsyncMock(return_value=sample_blocks_response)
            mock_client_class.return_value = mock_client

            service = NotionQueryService(
                api_key="test-key",
                database_id="test-db-id",
            )

            captures = await service.query_captures_by_date_range(
                start_date=datetime(2026, 1, 15),
                end_date=datetime(2026, 1, 25),
            )

            # Should have combined results from both pages
            assert len(captures) == 2

            # Should have made two query calls
            assert mock_client.databases.query.call_count == 2

            # Second call should include start_cursor
            second_call = mock_client.databases.query.call_args_list[1]
            assert second_call[1]["start_cursor"] == "cursor-abc-123"

    @pytest.mark.asyncio
    async def test_retry_on_server_error(self, sample_database_response, sample_blocks_response):
        """Test retry logic on server error (5xx)."""
        with patch("src.synthesis.notion_query.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()

            # Create mock 500 error
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.headers = {}
            error_500 = HTTPResponseError(mock_response, "Server error")
            error_500.status = 500

            # First two calls fail, third succeeds
            mock_client.databases.query = AsyncMock(
                side_effect=[error_500, error_500, sample_database_response]
            )
            mock_client.blocks.children.list = AsyncMock(return_value=sample_blocks_response)
            mock_client_class.return_value = mock_client

            service = NotionQueryService(
                api_key="test-key",
                database_id="test-db-id",
            )

            # Patch sleep to speed up test
            with patch("asyncio.sleep", new_callable=AsyncMock):
                captures = await service.query_captures_by_date_range(
                    start_date=datetime(2026, 1, 15),
                    end_date=datetime(2026, 1, 25),
                )

            assert len(captures) == 2
            assert mock_client.databases.query.call_count == 3

    @pytest.mark.asyncio
    async def test_rate_limit_handling(self, sample_database_response, sample_blocks_response):
        """Test rate limit (429) handling with retry."""
        with patch("src.synthesis.notion_query.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()

            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.headers = {"Retry-After": "0.1"}
            error_429 = HTTPResponseError(mock_response, "Rate limited")
            error_429.status = 429
            error_429.response = mock_response

            # First call rate limited, second succeeds
            mock_client.databases.query = AsyncMock(
                side_effect=[error_429, sample_database_response]
            )
            mock_client.blocks.children.list = AsyncMock(return_value=sample_blocks_response)
            mock_client_class.return_value = mock_client

            service = NotionQueryService(
                api_key="test-key",
                database_id="test-db-id",
            )

            with patch("asyncio.sleep", new_callable=AsyncMock):
                captures = await service.query_captures_by_date_range(
                    start_date=datetime(2026, 1, 15),
                    end_date=datetime(2026, 1, 25),
                )

            assert len(captures) == 2
            assert mock_client.databases.query.call_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_error_after_max_retries(self):
        """Test NotionQueryRateLimitError raised after max retries."""
        with patch("src.synthesis.notion_query.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()

            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.headers = {"Retry-After": "0.01"}
            error_429 = HTTPResponseError(mock_response, "Rate limited")
            error_429.status = 429
            error_429.response = mock_response

            mock_client.databases.query = AsyncMock(side_effect=error_429)
            mock_client_class.return_value = mock_client

            service = NotionQueryService(
                api_key="test-key",
                database_id="test-db-id",
                max_retries=2,
            )

            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(NotionQueryRateLimitError) as exc_info:
                    await service.query_captures_by_date_range(
                        start_date=datetime(2026, 1, 15),
                        end_date=datetime(2026, 1, 25),
                    )

            assert exc_info.value.retry_after > 0

    @pytest.mark.asyncio
    async def test_client_error_no_retry(self):
        """Test client error (4xx except 429) fails immediately."""
        with patch("src.synthesis.notion_query.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()

            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.headers = {}
            error_400 = HTTPResponseError(mock_response, "Bad request")
            error_400.status = 400

            mock_client.databases.query = AsyncMock(side_effect=error_400)
            mock_client_class.return_value = mock_client

            service = NotionQueryService(
                api_key="test-key",
                database_id="test-db-id",
            )

            with pytest.raises(NotionQueryError) as exc_info:
                await service.query_captures_by_date_range(
                    start_date=datetime(2026, 1, 15),
                    end_date=datetime(2026, 1, 25),
                )

            assert "Client error" in str(exc_info.value)
            # Should only be called once (no retries)
            assert mock_client.databases.query.call_count == 1


# ============================================================================
# Property Extraction Tests
# ============================================================================

class TestPropertyExtraction:
    """Tests for Notion property extraction methods."""

    def test_extract_title(self):
        """Test title extraction from properties."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        properties = {
            "Title": {
                "type": "title",
                "title": [
                    {"plain_text": "First part"},
                    {"plain_text": " second part"}
                ]
            }
        }

        title = service._extract_title(properties)
        assert title == "First part second part"

    def test_extract_title_fallback_to_name(self):
        """Test title extraction falls back to Name property."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        properties = {
            "Name": {
                "type": "title",
                "title": [{"plain_text": "Name title"}]
            }
        }

        title = service._extract_title(properties)
        assert title == "Name title"

    def test_extract_title_missing(self):
        """Test title extraction returns Untitled when missing."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        title = service._extract_title({})
        assert title == "Untitled"

    def test_extract_date_with_time(self):
        """Test date extraction with time component."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        properties = {
            "Date": {
                "type": "date",
                "date": {"start": "2026-01-20T14:30:00"}
            }
        }

        date = service._extract_date(properties, "Date")
        assert date == datetime(2026, 1, 20, 14, 30, 0)

    def test_extract_date_without_time(self):
        """Test date extraction without time component."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        properties = {
            "Date": {
                "type": "date",
                "date": {"start": "2026-01-20"}
            }
        }

        date = service._extract_date(properties, "Date")
        assert date.year == 2026
        assert date.month == 1
        assert date.day == 20

    def test_extract_date_missing(self):
        """Test date extraction returns None when missing."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        date = service._extract_date({}, "Date")
        assert date is None

    def test_extract_select(self):
        """Test select property extraction."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        properties = {
            "Type": {
                "type": "select",
                "select": {"name": "Task"}
            }
        }

        value = service._extract_select(properties, "Type")
        assert value == "Task"

    def test_extract_select_missing(self):
        """Test select extraction returns None when missing."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        value = service._extract_select({}, "Type")
        assert value is None

    def test_extract_multi_select(self):
        """Test multi_select property extraction."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        properties = {
            "Tags": {
                "type": "multi_select",
                "multi_select": [
                    {"name": "work"},
                    {"name": "urgent"},
                    {"name": "review"}
                ]
            }
        }

        tags = service._extract_multi_select(properties, "Tags")
        assert tags == ["work", "urgent", "review"]

    def test_extract_multi_select_empty(self):
        """Test multi_select extraction returns empty list."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        tags = service._extract_multi_select({}, "Tags")
        assert tags == []


# ============================================================================
# Block Text Extraction Tests
# ============================================================================

class TestBlockTextExtraction:
    """Tests for Notion block text extraction."""

    def test_extract_paragraph_text(self):
        """Test extracting text from paragraph block."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        block = {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"plain_text": "Test paragraph."}]
            }
        }

        text = service._extract_block_text(block)
        assert text == "Test paragraph."

    def test_extract_heading_text(self):
        """Test extracting text from heading blocks."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        heading1 = {
            "type": "heading_1",
            "heading_1": {"rich_text": [{"plain_text": "Main Title"}]}
        }
        heading2 = {
            "type": "heading_2",
            "heading_2": {"rich_text": [{"plain_text": "Section"}]}
        }
        heading3 = {
            "type": "heading_3",
            "heading_3": {"rich_text": [{"plain_text": "Subsection"}]}
        }

        assert service._extract_block_text(heading1) == "# Main Title"
        assert service._extract_block_text(heading2) == "## Section"
        assert service._extract_block_text(heading3) == "### Subsection"

    def test_extract_list_item_text(self):
        """Test extracting text from list items."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        bulleted = {
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"plain_text": "Bullet point"}]}
        }
        numbered = {
            "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": [{"plain_text": "Numbered item"}]}
        }

        assert service._extract_block_text(bulleted) == "- Bullet point"
        assert service._extract_block_text(numbered) == "1. Numbered item"

    def test_extract_quote_text(self):
        """Test extracting text from quote block."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        quote = {
            "type": "quote",
            "quote": {"rich_text": [{"plain_text": "Quoted text"}]}
        }

        assert service._extract_block_text(quote) == "> Quoted text"

    def test_extract_unsupported_block(self):
        """Test unsupported block types return empty string."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        block = {
            "type": "divider",
            "divider": {}
        }

        assert service._extract_block_text(block) == ""


# ============================================================================
# group_by_template Tests
# ============================================================================

class TestGroupByTemplate:
    """Tests for group_by_template function."""

    def test_group_captures_by_template(self):
        """Test grouping captures by template type."""
        captures = [
            VoiceCapture(
                id="1", url="", title="Task 1",
                captured_at=datetime(2026, 1, 20),
                template_type="Task", device="Watch"
            ),
            VoiceCapture(
                id="2", url="", title="Journal 1",
                captured_at=datetime(2026, 1, 20),
                template_type="Journal", device="Phone"
            ),
            VoiceCapture(
                id="3", url="", title="Task 2",
                captured_at=datetime(2026, 1, 21),
                template_type="Task", device="Watch"
            ),
            VoiceCapture(
                id="4", url="", title="Idea 1",
                captured_at=datetime(2026, 1, 21),
                template_type="Idea", device="Phone"
            ),
        ]

        grouped = group_by_template(captures)

        assert len(grouped) == 3
        assert len(grouped["Task"]) == 2
        assert len(grouped["Journal"]) == 1
        assert len(grouped["Idea"]) == 1
        assert grouped["Task"][0].title == "Task 1"
        assert grouped["Task"][1].title == "Task 2"

    def test_group_empty_list(self):
        """Test grouping empty list returns empty dict."""
        grouped = group_by_template([])
        assert grouped == {}

    def test_group_single_type(self):
        """Test grouping when all captures have same type."""
        captures = [
            VoiceCapture(
                id="1", url="", title="Journal 1",
                captured_at=datetime(2026, 1, 20),
                template_type="Journal", device="Watch"
            ),
            VoiceCapture(
                id="2", url="", title="Journal 2",
                captured_at=datetime(2026, 1, 21),
                template_type="Journal", device="Phone"
            ),
        ]

        grouped = group_by_template(captures)

        assert len(grouped) == 1
        assert "Journal" in grouped
        assert len(grouped["Journal"]) == 2

    def test_group_handles_none_template(self):
        """Test grouping handles None template_type as General."""
        captures = [
            VoiceCapture(
                id="1", url="", title="No Type",
                captured_at=datetime(2026, 1, 20),
                template_type=None,  # type: ignore
                device="Watch"
            ),
        ]

        grouped = group_by_template(captures)

        assert "General" in grouped
        assert len(grouped["General"]) == 1


# ============================================================================
# Convenience Function Tests
# ============================================================================

class TestConvenienceFunction:
    """Tests for query_captures_by_date_range convenience function."""

    @pytest.mark.asyncio
    async def test_convenience_function(self, sample_database_response, sample_blocks_response):
        """Test the standalone convenience function."""
        with patch("src.synthesis.notion_query.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.databases.query = AsyncMock(return_value=sample_database_response)
            mock_client.blocks.children.list = AsyncMock(return_value=sample_blocks_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            captures = await query_captures_by_date_range(
                api_key="test-key",
                database_id="test-db-id",
                start_date=datetime(2026, 1, 15),
                end_date=datetime(2026, 1, 25),
            )

            assert len(captures) == 2
            # Verify close was called
            mock_client.aclose.assert_called_once()


# ============================================================================
# Date Filter Tests
# ============================================================================

class TestDateFilter:
    """Tests for date range filter building."""

    def test_build_date_range_filter(self):
        """Test date range filter structure."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        start_date = datetime(2026, 1, 15)
        end_date = datetime(2026, 1, 25)

        filter_params = service._build_date_range_filter(start_date, end_date)

        assert "and" in filter_params
        assert len(filter_params["and"]) == 2

        # Check start condition
        start_cond = filter_params["and"][0]
        assert start_cond["property"] == "Date"
        assert start_cond["date"]["on_or_after"] == "2026-01-15"

        # Check end condition
        end_cond = filter_params["and"][1]
        assert end_cond["property"] == "Date"
        assert end_cond["date"]["on_or_before"] == "2026-01-25"


# ============================================================================
# Backoff Calculation Tests
# ============================================================================

class TestBackoffCalculation:
    """Tests for exponential backoff calculation."""

    def test_backoff_calculation(self):
        """Test exponential backoff with jitter."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        # Attempt 0: ~5s + jitter
        backoff_0 = service._calculate_backoff(0)
        assert 5.0 <= backoff_0 <= 5.5

        # Attempt 1: ~10s + jitter
        backoff_1 = service._calculate_backoff(1)
        assert 10.0 <= backoff_1 <= 11.0

        # Attempt 2: ~20s + jitter
        backoff_2 = service._calculate_backoff(2)
        assert 20.0 <= backoff_2 <= 22.0

    def test_extract_retry_after(self):
        """Test Retry-After header extraction."""
        service = NotionQueryService(
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
        """Test default Retry-After when header missing."""
        service = NotionQueryService(
            api_key="test-key",
            database_id="test-db-id",
        )

        mock_response = MagicMock()
        mock_response.headers = {}
        error = HTTPResponseError(mock_response, "Rate limited")
        error.response = mock_response

        retry_after = service._extract_retry_after(error)
        assert retry_after == 1.0
