"""Unit tests for the Pushover notification service.

Tests cover:
- Basic notification sending with various parameters
- Processing failure notifications
- Daily summary notifications
- High failure rate alerts
- Queue backup alerts
- Rate limiting behavior
- Error handling
- Disabled notifications
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from src.notifications.pushover import (
    PushoverService,
    NotificationPriority,
    DailyStats,
)


class TestNotificationPriority:
    """Tests for NotificationPriority enum."""

    def test_priority_values(self):
        """Verify priority values match Pushover API spec."""
        assert NotificationPriority.LOWEST == -2
        assert NotificationPriority.LOW == -1
        assert NotificationPriority.NORMAL == 0
        assert NotificationPriority.HIGH == 1
        assert NotificationPriority.EMERGENCY == 2

    def test_priority_is_int(self):
        """Verify priorities can be used as integers."""
        assert int(NotificationPriority.NORMAL) == 0
        assert NotificationPriority.HIGH + 1 == 2


class TestDailyStats:
    """Tests for DailyStats dataclass."""

    def test_failure_rate_calculation(self):
        """Test failure rate is calculated correctly."""
        stats = DailyStats(
            date="2026-01-20",
            completed=8,
            failed=2,
            pending=0,
        )
        assert stats.failure_rate == 0.2  # 2/10 = 0.2

    def test_failure_rate_no_captures(self):
        """Test failure rate with no captures returns 0."""
        stats = DailyStats(
            date="2026-01-20",
            completed=0,
            failed=0,
            pending=0,
        )
        assert stats.failure_rate == 0.0

    def test_failure_rate_all_failed(self):
        """Test failure rate when all captures failed."""
        stats = DailyStats(
            date="2026-01-20",
            completed=0,
            failed=5,
            pending=0,
        )
        assert stats.failure_rate == 1.0

    def test_failure_rate_all_successful(self):
        """Test failure rate when all captures succeeded."""
        stats = DailyStats(
            date="2026-01-20",
            completed=10,
            failed=0,
            pending=0,
        )
        assert stats.failure_rate == 0.0


class TestPushoverServiceInit:
    """Tests for PushoverService initialization."""

    def test_init_basic(self):
        """Test basic initialization."""
        service = PushoverService(
            api_token="test-token",
            user_key="test-user",
        )
        assert service.api_token == "test-token"
        assert service.user_key == "test-user"
        assert service.device is None
        assert service.enabled is True

    def test_init_with_device(self):
        """Test initialization with specific device."""
        service = PushoverService(
            api_token="test-token",
            user_key="test-user",
            device="my-phone",
        )
        assert service.device == "my-phone"

    def test_init_disabled(self):
        """Test initialization with notifications disabled."""
        service = PushoverService(
            api_token="test-token",
            user_key="test-user",
            enabled=False,
        )
        assert service.enabled is False


class TestSendNotification:
    """Tests for send_notification method."""

    @pytest.fixture
    def service(self):
        """Create a test PushoverService instance."""
        return PushoverService(
            api_token="test-token",
            user_key="test-user",
        )

    @pytest.mark.asyncio
    async def test_send_notification_success(self, service):
        """Test successful notification sending."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='{"status":1}')

            mock_post = AsyncMock(return_value=mock_response)
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await service.send_notification(
                title="Test Title",
                message="Test message",
            )

            assert result is True
            mock_session.post.assert_called_once()
            call_kwargs = mock_session.post.call_args
            assert call_kwargs[0][0] == service.PUSHOVER_API_URL

    @pytest.mark.asyncio
    async def test_send_notification_disabled(self, service):
        """Test that disabled service returns True without sending."""
        service.enabled = False

        with patch("aiohttp.ClientSession") as mock_session:
            result = await service.send_notification(
                title="Test",
                message="Test",
            )

            assert result is True
            mock_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_notification_no_credentials(self):
        """Test that missing credentials returns False."""
        service = PushoverService(api_token="", user_key="")

        result = await service.send_notification(
            title="Test",
            message="Test",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_notification_api_error(self, service):
        """Test handling of API errors."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 400
            mock_response.text = AsyncMock(return_value='{"errors":["invalid token"]}')

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await service.send_notification(
                title="Test",
                message="Test",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_send_notification_network_error(self, service):
        """Test handling of network errors."""
        with patch("src.notifications.pushover.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()

            # Make the session context manager raise an aiohttp.ClientError
            async def raise_on_enter(mock_self):
                raise aiohttp.ClientError("Connection failed")

            mock_session.__aenter__ = raise_on_enter
            mock_session.__aexit__ = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await service.send_notification(
                title="Test",
                message="Test",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_send_notification_with_url(self, service):
        """Test notification with URL parameters."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='{"status":1}')

            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()))
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session_class.return_value = mock_session

            result = await service.send_notification(
                title="Test",
                message="Test",
                url="https://notion.so/page-123",
                url_title="View in Notion",
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_send_notification_truncates_long_inputs(self, service):
        """Test that long inputs are truncated to API limits."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='{"status":1}')

            mock_session = MagicMock()
            captured_data = {}

            def capture_post(url, data, timeout):
                captured_data.update(data)
                return AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock())

            mock_session.post = MagicMock(side_effect=capture_post)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session_class.return_value = mock_session

            long_title = "A" * 500  # Over 250 char limit
            long_message = "B" * 2000  # Over 1024 char limit

            result = await service.send_notification(
                title=long_title,
                message=long_message,
            )

            assert result is True
            assert len(captured_data["title"]) == 250
            assert len(captured_data["message"]) == 1024

    @pytest.mark.asyncio
    async def test_send_notification_clamps_priority(self, service):
        """Test that invalid priorities are clamped to valid range."""
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='{"status":1}')

            mock_session = MagicMock()
            captured_data = {}

            def capture_post(url, data, timeout):
                captured_data.update(data)
                return AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock())

            mock_session.post = MagicMock(side_effect=capture_post)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session_class.return_value = mock_session

            # Test priority too high
            await service.send_notification(
                title="Test",
                message="Test",
                priority=10,
            )
            assert captured_data["priority"] == 2

            # Reset rate limit
            service._last_notification_time = None

            # Test priority too low
            await service.send_notification(
                title="Test",
                message="Test",
                priority=-10,
            )
            assert captured_data["priority"] == -2


class TestNotifyProcessingFailure:
    """Tests for notify_processing_failure method."""

    @pytest.fixture
    def service(self):
        """Create a test PushoverService instance."""
        return PushoverService(
            api_token="test-token",
            user_key="test-user",
        )

    @pytest.mark.asyncio
    async def test_notify_processing_failure(self, service):
        """Test processing failure notification."""
        with patch.object(service, "send_notification", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await service.notify_processing_failure(
                filename="2026-01-20T143022_watch.m4a",
                error_message="Notion API timeout",
                stage="posting",
            )

            assert result is True
            mock_send.assert_called_once()

            # Verify call arguments
            call_kwargs = mock_send.call_args[1]
            assert "Processing Failed" in call_kwargs["title"]
            assert "2026-01-20T143022_watch.m4a" in call_kwargs["message"]
            assert "Notion API timeout" in call_kwargs["message"]
            assert "posting" in call_kwargs["message"]
            assert call_kwargs["priority"] == NotificationPriority.NORMAL

    @pytest.mark.asyncio
    async def test_notify_processing_failure_with_url(self, service):
        """Test processing failure notification with Notion URL."""
        with patch.object(service, "send_notification", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await service.notify_processing_failure(
                filename="test.m4a",
                error_message="Error",
                stage="classifying",
                notion_page_url="https://notion.so/page-123",
            )

            assert result is True
            call_kwargs = mock_send.call_args[1]
            assert call_kwargs["url"] == "https://notion.so/page-123"
            assert call_kwargs["url_title"] == "View in Notion"


class TestSendDailySummary:
    """Tests for send_daily_summary method."""

    @pytest.fixture
    def service(self):
        """Create a test PushoverService instance."""
        return PushoverService(
            api_token="test-token",
            user_key="test-user",
        )

    @pytest.mark.asyncio
    async def test_send_daily_summary(self, service):
        """Test daily summary notification."""
        with patch.object(service, "send_notification", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            stats = DailyStats(
                date="2026-01-20",
                completed=8,
                failed=2,
                pending=3,
                total_audio_seconds=600.0,
            )

            result = await service.send_daily_summary(stats)

            assert result is True
            mock_send.assert_called_once()

            call_kwargs = mock_send.call_args[1]
            assert "2026-01-20" in call_kwargs["title"]
            assert "8 processed" in call_kwargs["message"]
            assert "2 failed" in call_kwargs["message"]
            assert "3 pending" in call_kwargs["message"]
            assert "10.0 min" in call_kwargs["message"]  # 600s = 10min
            assert "20.0%" in call_kwargs["message"]  # 2/10 = 20%
            assert call_kwargs["priority"] == NotificationPriority.LOW

    @pytest.mark.asyncio
    async def test_send_daily_summary_no_failures(self, service):
        """Test daily summary with no failures."""
        with patch.object(service, "send_notification", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            stats = DailyStats(
                date="2026-01-20",
                completed=10,
                failed=0,
                pending=0,
            )

            result = await service.send_daily_summary(stats)

            assert result is True
            call_kwargs = mock_send.call_args[1]
            # Should not include failure rate line when no failures
            assert "Failure rate" not in call_kwargs["message"]


class TestNotifyHighFailureRate:
    """Tests for notify_high_failure_rate method."""

    @pytest.fixture
    def service(self):
        """Create a test PushoverService instance."""
        return PushoverService(
            api_token="test-token",
            user_key="test-user",
        )

    @pytest.mark.asyncio
    async def test_notify_high_failure_rate(self, service):
        """Test high failure rate alert."""
        with patch.object(service, "send_notification", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await service.notify_high_failure_rate(
                failure_rate=0.25,
                failed_count=5,
                total_count=20,
            )

            assert result is True
            mock_send.assert_called_once()

            call_kwargs = mock_send.call_args[1]
            assert "High Failure Rate" in call_kwargs["title"]
            assert "25.0%" in call_kwargs["message"]
            assert "5/20" in call_kwargs["message"]
            assert call_kwargs["priority"] == NotificationPriority.HIGH


class TestNotifyQueueBackup:
    """Tests for notify_queue_backup method."""

    @pytest.fixture
    def service(self):
        """Create a test PushoverService instance."""
        return PushoverService(
            api_token="test-token",
            user_key="test-user",
        )

    @pytest.mark.asyncio
    async def test_notify_queue_backup(self, service):
        """Test queue backup alert."""
        with patch.object(service, "send_notification", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await service.notify_queue_backup(pending_count=15)

            assert result is True
            mock_send.assert_called_once()

            call_kwargs = mock_send.call_args[1]
            assert "Queue Backed Up" in call_kwargs["title"]
            assert "15 items pending" in call_kwargs["message"]
            assert call_kwargs["priority"] == NotificationPriority.NORMAL


class TestRateLimiting:
    """Tests for rate limiting behavior."""

    @pytest.fixture
    def service(self):
        """Create a test PushoverService instance."""
        return PushoverService(
            api_token="test-token",
            user_key="test-user",
        )

    def test_check_rate_limit_no_previous(self, service):
        """Test rate limit allows first notification."""
        assert service._check_rate_limit() is True

    def test_check_rate_limit_recent_notification(self, service):
        """Test rate limit blocks rapid notifications."""
        service._last_notification_time = datetime.now()
        assert service._check_rate_limit() is False

    def test_check_rate_limit_after_interval(self, service):
        """Test rate limit allows notification after interval."""
        service._last_notification_time = datetime.now() - timedelta(seconds=15)
        assert service._check_rate_limit() is True

    @pytest.mark.asyncio
    async def test_rate_limit_skips_notification(self, service):
        """Test that rate limited notifications are skipped."""
        service._last_notification_time = datetime.now()

        with patch("aiohttp.ClientSession") as mock_session:
            result = await service.send_notification(
                title="Test",
                message="Test",
            )

            assert result is False
            mock_session.assert_not_called()


class TestIntegration:
    """Integration tests for the notification service."""

    @pytest.fixture
    def service(self):
        """Create a test PushoverService instance."""
        return PushoverService(
            api_token="test-token",
            user_key="test-user",
        )

    @pytest.mark.asyncio
    async def test_full_daily_summary_flow(self, service):
        """Test complete daily summary flow including high failure rate check."""
        with patch.object(service, "send_notification", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            stats = DailyStats(
                date="2026-01-20",
                completed=6,
                failed=4,  # 40% failure rate
                pending=5,
                total_audio_seconds=300.0,
            )

            # Send daily summary
            await service.send_daily_summary(stats)

            # Check if we should alert for high failure rate (>20%)
            if stats.failure_rate > 0.2:
                await service.notify_high_failure_rate(
                    failure_rate=stats.failure_rate,
                    failed_count=stats.failed,
                    total_count=stats.completed + stats.failed,
                )

            # Check if we should alert for queue backup (>10 items)
            if stats.pending > 10:
                await service.notify_queue_backup(stats.pending)

            # Should have called send twice (summary + high failure rate)
            assert mock_send.call_count == 2

    @pytest.mark.asyncio
    async def test_notification_with_device_filter(self):
        """Test notification sent to specific device."""
        service = PushoverService(
            api_token="test-token",
            user_key="test-user",
            device="my-iphone",
        )

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='{"status":1}')

            captured_data = {}

            def capture_post(url, data, timeout):
                captured_data.update(data)
                return AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock())

            mock_session = MagicMock()
            mock_session.post = MagicMock(side_effect=capture_post)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session_class.return_value = mock_session

            await service.send_notification(
                title="Test",
                message="Test",
            )

            assert captured_data["device"] == "my-iphone"
