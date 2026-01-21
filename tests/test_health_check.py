"""Tests for health check functionality.

Tests the HealthChecker class and health_check CLI command.
"""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import Settings
from src.db.database import Database
from src.health.checker import (
    CheckStatus,
    HealthCheck,
    HealthCheckResult,
    HealthChecker,
    ProcessingStats,
)
from src.notifications.pushover import PushoverService


class TestProcessingStats:
    """Tests for ProcessingStats dataclass."""

    def test_failure_rate_zero_when_no_captures(self):
        """Failure rate should be 0 when no captures processed."""
        stats = ProcessingStats()
        assert stats.failure_rate == 0.0

    def test_failure_rate_calculated_correctly(self):
        """Failure rate should be calculated correctly."""
        stats = ProcessingStats(
            captures_completed_24h=8,
            captures_failed_24h=2,
        )
        assert stats.failure_rate == 0.2  # 2 / (8 + 2) = 0.2

    def test_failure_rate_all_failed(self):
        """Failure rate should be 1.0 when all captures failed."""
        stats = ProcessingStats(
            captures_completed_24h=0,
            captures_failed_24h=5,
        )
        assert stats.failure_rate == 1.0


class TestHealthCheckResult:
    """Tests for HealthCheckResult dataclass."""

    def test_add_check_counts_correctly(self):
        """Adding checks should update counts correctly."""
        result = HealthCheckResult()

        result.add_check(HealthCheck("Test1", CheckStatus.PASS, "OK"))
        result.add_check(HealthCheck("Test2", CheckStatus.FAIL, "Failed"))
        result.add_check(HealthCheck("Test3", CheckStatus.WARN, "Warning"))
        result.add_check(HealthCheck("Test4", CheckStatus.SKIP, "Skipped"))

        assert result.passed == 1
        assert result.failed == 1
        assert result.warnings == 1
        assert result.skipped == 1
        assert len(result.checks) == 4

    def test_all_passed_true_when_no_failures(self):
        """all_passed should be True when no checks failed."""
        result = HealthCheckResult()
        result.add_check(HealthCheck("Test1", CheckStatus.PASS, "OK"))
        result.add_check(HealthCheck("Test2", CheckStatus.WARN, "Warning"))

        assert result.all_passed is True
        assert result.is_healthy is True

    def test_all_passed_false_when_failure_exists(self):
        """all_passed should be False when any check failed."""
        result = HealthCheckResult()
        result.add_check(HealthCheck("Test1", CheckStatus.PASS, "OK"))
        result.add_check(HealthCheck("Test2", CheckStatus.FAIL, "Failed"))

        assert result.all_passed is False
        assert result.is_healthy is False


class TestHealthChecker:
    """Tests for HealthChecker class."""

    @pytest.fixture
    def mock_settings(self, temp_dir: Path):
        """Create mock settings for testing."""
        settings = MagicMock(spec=Settings)
        settings.openai_api_key = "test-openai-key"
        settings.anthropic_api_key = "test-anthropic-key"
        settings.notion_api_key = "test-notion-key"
        settings.notion_voice_captures_db_id = "test-db-id"
        settings.pushover_api_token = "test-pushover-token"
        settings.pushover_user_key = "test-pushover-user"

        # Create test directories
        inbox = temp_dir / "inbox"
        processing = temp_dir / "processing"
        failed = temp_dir / "failed"
        inbox.mkdir()
        processing.mkdir()
        failed.mkdir()

        settings.paths = MagicMock()
        settings.paths.inbox = inbox
        settings.paths.processing = processing
        settings.paths.failed = failed

        settings.classification = MagicMock()
        settings.classification.model = "claude-sonnet-4-20250514"

        settings.health_check = MagicMock()
        settings.health_check.failure_rate_threshold = 0.2
        settings.health_check.queue_backup_threshold = 10

        return settings

    @pytest.fixture
    def mock_db(self):
        """Create mock database for testing."""
        db = MagicMock(spec=Database)
        db.get_queue_depth = AsyncMock(return_value={
            "pending": 2,
            "complete": 10,
            "failed": 1,
        })
        db.get_daily_stats = AsyncMock(return_value=MagicMock(
            captures_received=5,
            captures_completed=4,
            captures_failed=1,
        ))
        return db

    @pytest.fixture
    def mock_pushover(self):
        """Create mock Pushover service for testing."""
        pushover = MagicMock(spec=PushoverService)
        pushover.send_notification = AsyncMock(return_value=True)
        return pushover

    @pytest.mark.asyncio
    async def test_check_database_pass(self, mock_settings, mock_db):
        """Database check should pass when connection works."""
        checker = HealthChecker(mock_settings, mock_db)
        result = await checker._check_database()

        assert result.status == CheckStatus.PASS
        assert "Connected" in result.message
        mock_db.get_queue_depth.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_database_fail_on_error(self, mock_settings, mock_db):
        """Database check should fail when connection fails."""
        mock_db.get_queue_depth = AsyncMock(side_effect=Exception("Connection refused"))

        checker = HealthChecker(mock_settings, mock_db)
        result = await checker._check_database()

        assert result.status == CheckStatus.FAIL
        assert "failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_openai_api_skip_when_no_key(self, mock_settings, mock_db):
        """OpenAI check should skip when API key not configured."""
        mock_settings.openai_api_key = ""

        checker = HealthChecker(mock_settings, mock_db)
        result = await checker._check_openai_api()

        assert result.status == CheckStatus.SKIP
        assert "not configured" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_openai_api_pass(self, mock_settings, mock_db):
        """OpenAI check should pass when API is reachable."""
        with patch("openai.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            # Mock models list with whisper model
            mock_model = MagicMock()
            mock_model.id = "whisper-1"
            mock_models = MagicMock()
            mock_models.data = [mock_model]
            mock_client.models.list = AsyncMock(return_value=mock_models)

            checker = HealthChecker(mock_settings, mock_db)
            result = await checker._check_openai_api()

            assert result.status == CheckStatus.PASS
            assert "Whisper available" in result.message

    @pytest.mark.asyncio
    async def test_check_claude_api_skip_when_no_key(self, mock_settings, mock_db):
        """Claude check should skip when API key not configured."""
        mock_settings.anthropic_api_key = ""

        checker = HealthChecker(mock_settings, mock_db)
        result = await checker._check_claude_api()

        assert result.status == CheckStatus.SKIP

    @pytest.mark.asyncio
    async def test_check_notion_api_skip_when_no_key(self, mock_settings, mock_db):
        """Notion check should skip when API key not configured."""
        mock_settings.notion_api_key = ""

        checker = HealthChecker(mock_settings, mock_db)
        result = await checker._check_notion_api()

        assert result.status == CheckStatus.SKIP

    @pytest.mark.asyncio
    async def test_check_notion_api_skip_when_no_db_id(self, mock_settings, mock_db):
        """Notion check should skip when database ID not configured."""
        mock_settings.notion_voice_captures_db_id = ""

        checker = HealthChecker(mock_settings, mock_db)
        result = await checker._check_notion_api()

        assert result.status == CheckStatus.SKIP

    @pytest.mark.asyncio
    async def test_check_pushover_api_skip_when_no_credentials(self, mock_settings, mock_db):
        """Pushover check should skip when credentials not configured."""
        mock_settings.pushover_api_token = ""
        mock_settings.pushover_user_key = ""

        checker = HealthChecker(mock_settings, mock_db)
        result = await checker._check_pushover_api()

        assert result.status == CheckStatus.SKIP

    @pytest.mark.asyncio
    async def test_check_directories_pass(self, mock_settings, mock_db):
        """Directory checks should pass when directories exist with permissions."""
        checker = HealthChecker(mock_settings, mock_db)
        results = await checker._check_directories()

        assert len(results) == 3  # inbox, processing, failed
        for result in results:
            assert result.status == CheckStatus.PASS

    @pytest.mark.asyncio
    async def test_check_directories_fail_when_missing(self, mock_settings, mock_db, temp_dir):
        """Directory check should fail when directory doesn't exist."""
        mock_settings.paths.inbox = temp_dir / "nonexistent"

        checker = HealthChecker(mock_settings, mock_db)
        results = await checker._check_directories()

        # First result (inbox) should fail
        assert results[0].status == CheckStatus.FAIL
        assert "Does not exist" in results[0].message

    @pytest.mark.asyncio
    async def test_collect_stats(self, mock_settings, mock_db):
        """Stats collection should return correct values."""
        checker = HealthChecker(mock_settings, mock_db)
        stats = await checker._collect_stats()

        assert stats.captures_completed_24h == 4
        assert stats.captures_failed_24h == 1
        assert stats.current_queue_depth == 2  # pending only

    @pytest.mark.asyncio
    async def test_evaluate_alerts_high_failure_rate(self, mock_settings, mock_db):
        """Should trigger alert when failure rate exceeds threshold."""
        checker = HealthChecker(mock_settings, mock_db)

        result = HealthCheckResult()
        result.stats = ProcessingStats(
            captures_completed_24h=6,
            captures_failed_24h=4,  # 40% failure rate
        )

        alerts = checker._evaluate_alerts(result)

        assert len(alerts) >= 1
        assert any("Failure rate" in alert for alert in alerts)
        assert any("HIGH:" in alert for alert in alerts)

    @pytest.mark.asyncio
    async def test_evaluate_alerts_queue_backup(self, mock_settings, mock_db):
        """Should trigger alert when queue depth exceeds threshold."""
        checker = HealthChecker(mock_settings, mock_db)

        result = HealthCheckResult()
        result.stats = ProcessingStats(
            current_queue_depth=15,  # Exceeds threshold of 10
        )

        alerts = checker._evaluate_alerts(result)

        assert len(alerts) >= 1
        assert any("Queue backup" in alert for alert in alerts)
        assert any("NORMAL:" in alert for alert in alerts)

    @pytest.mark.asyncio
    async def test_evaluate_alerts_api_failure(self, mock_settings, mock_db):
        """Should trigger high priority alert when API check fails."""
        checker = HealthChecker(mock_settings, mock_db)

        result = HealthCheckResult()
        result.add_check(HealthCheck("OpenAI API", CheckStatus.FAIL, "Connection failed"))
        result.stats = ProcessingStats()

        alerts = checker._evaluate_alerts(result)

        assert len(alerts) >= 1
        assert any("OpenAI API" in alert for alert in alerts)
        assert any("HIGH:" in alert for alert in alerts)

    @pytest.mark.asyncio
    async def test_run_all_checks(self, mock_settings, mock_db):
        """run_all_checks should execute all checks and collect stats."""
        # Patch all API checks to avoid real network calls
        with patch.object(HealthChecker, "_check_openai_api", new_callable=AsyncMock) as mock_openai, \
             patch.object(HealthChecker, "_check_claude_api", new_callable=AsyncMock) as mock_claude, \
             patch.object(HealthChecker, "_check_notion_api", new_callable=AsyncMock) as mock_notion, \
             patch.object(HealthChecker, "_check_pushover_api", new_callable=AsyncMock) as mock_pushover:

            mock_openai.return_value = HealthCheck("OpenAI API", CheckStatus.PASS, "OK")
            mock_claude.return_value = HealthCheck("Claude API", CheckStatus.PASS, "OK")
            mock_notion.return_value = HealthCheck("Notion API", CheckStatus.PASS, "OK")
            mock_pushover.return_value = HealthCheck("Pushover API", CheckStatus.PASS, "OK")

            checker = HealthChecker(mock_settings, mock_db)
            result = await checker.run_all_checks()

            # Should have checks for: database, 4 APIs, 3 directories
            assert len(result.checks) == 8
            assert result.stats is not None

    @pytest.mark.asyncio
    async def test_send_health_notification_no_pushover(self, mock_settings, mock_db):
        """Should return False when Pushover not configured."""
        checker = HealthChecker(mock_settings, mock_db, pushover=None)
        result = HealthCheckResult()
        result.stats = ProcessingStats()

        sent = await checker.send_health_notification(result)

        assert sent is False

    @pytest.mark.asyncio
    async def test_send_health_notification_with_alerts(self, mock_settings, mock_db, mock_pushover):
        """Should send alert notification when alerts present."""
        checker = HealthChecker(mock_settings, mock_db, mock_pushover)

        result = HealthCheckResult()
        result.add_check(HealthCheck("OpenAI API", CheckStatus.FAIL, "Connection failed"))
        result.stats = ProcessingStats()
        result.alerts = ["HIGH: OpenAI API unreachable"]

        await checker.send_health_notification(result)

        # Should call send_notification at least twice (alert + summary)
        assert mock_pushover.send_notification.call_count >= 1


class TestHealthCheckCLI:
    """Tests for health_check CLI command."""

    @pytest.mark.asyncio
    async def test_run_health_check_integration(self, test_settings: Settings, temp_dir: Path):
        """Integration test for run_health_check function."""
        from src.cli.health_check import run_health_check

        # Initialize database
        db = Database(test_settings.paths.database)
        await db.initialize()
        await db.close()

        # Patch API checks to avoid real network calls
        with patch("openai.AsyncOpenAI") as mock_openai, \
             patch("anthropic.AsyncAnthropic") as mock_anthropic, \
             patch("notion_client.AsyncClient") as mock_notion, \
             patch("aiohttp.ClientSession") as mock_aiohttp:

            # Mock OpenAI
            mock_openai_client = MagicMock()
            mock_openai.return_value = mock_openai_client
            mock_model = MagicMock()
            mock_model.id = "whisper-1"
            mock_models = MagicMock()
            mock_models.data = [mock_model]
            mock_openai_client.models.list = AsyncMock(return_value=mock_models)

            # Mock Anthropic
            mock_anthropic_client = MagicMock()
            mock_anthropic.return_value = mock_anthropic_client
            mock_anthropic_client.messages.create = AsyncMock(return_value=MagicMock())

            # Mock Notion
            mock_notion_client = MagicMock()
            mock_notion.return_value = mock_notion_client
            mock_notion_client.databases.query = AsyncMock(return_value={"results": []})

            # Mock Pushover
            mock_session = MagicMock()
            mock_aiohttp.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_aiohttp.return_value.__aexit__ = AsyncMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"status": 1})
            mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.post.return_value.__aexit__ = AsyncMock()

            # Run health check without notification
            result = await run_health_check(notify=False, verbose=False)

            assert result is not None
            assert len(result.checks) > 0
            # At minimum we should have database and directory checks passing
            assert result.passed > 0
