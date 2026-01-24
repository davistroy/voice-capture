"""Tests for health_check CLI command.

Tests the health check CLI functionality including
running checks, printing reports, and sending notifications.
"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from src.health.checker import CheckStatus, HealthCheckResult, ProcessingStats, HealthCheck


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def cli_runner():
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_settings(temp_dir: Path):
    """Create mock settings for testing."""
    settings = MagicMock()
    settings.openai_api_key = "test-openai-key"
    settings.anthropic_api_key = "test-anthropic-key"
    settings.notion_api_key = "test-notion-key"
    settings.notion_voice_captures_db_id = "test-db-id"
    settings.pushover_api_token = "test-pushover-token"
    settings.pushover_user_key = "test-pushover-user"

    settings.paths = MagicMock()
    settings.paths.inbox = temp_dir / "inbox"
    settings.paths.processing = temp_dir / "processing"
    settings.paths.failed = temp_dir / "failed"
    settings.paths.database = temp_dir / "data" / "voice_capture.db"
    settings.paths.logs = temp_dir / "logs"
    settings.paths.templates = temp_dir / "templates"

    return settings


def create_health_result(passed: bool = True, with_stats: bool = True, with_alerts: bool = False):
    """Create a health check result for testing."""
    result = HealthCheckResult(timestamp=datetime.utcnow())

    # Add checks using add_check method
    result.add_check(HealthCheck(
        name="Test Check 1",
        status=CheckStatus.PASS,
        message="All good",
        duration_ms=50.0,
    ))

    if passed:
        result.add_check(HealthCheck(
            name="Test Check 2",
            status=CheckStatus.PASS,
            message="OK",
            duration_ms=30.0,
        ))
    else:
        result.add_check(HealthCheck(
            name="Test Check 2",
            status=CheckStatus.FAIL,
            message="Connection failed",
            details="API timeout",
        ))

    if with_stats:
        result.stats = ProcessingStats(
            captures_received_24h=10,
            captures_completed_24h=8,
            captures_failed_24h=2,
            current_queue_depth=5,
            queue_by_status={"pending": 3, "failed": 2},
        )

    if with_alerts:
        result.alerts = ["HIGH: API connection failed"]

    return result


# ============================================================================
# Health Check Result Tests
# ============================================================================


class TestHealthCheckResult:
    """Tests for HealthCheckResult properties."""

    def test_is_healthy_all_pass(self):
        """Test is_healthy when all checks pass."""
        result = create_health_result(passed=True)
        assert result.is_healthy is True

    def test_is_healthy_with_failure(self):
        """Test is_healthy when some checks fail."""
        result = create_health_result(passed=False)
        assert result.is_healthy is False

    def test_passed_count(self):
        """Test passed count property."""
        result = create_health_result(passed=True)
        assert result.passed == 2

    def test_failed_count(self):
        """Test failed count property."""
        result = create_health_result(passed=False)
        assert result.failed == 1


# ============================================================================
# Print Health Report Tests
# ============================================================================


class TestPrintHealthReport:
    """Tests for print_health_report function."""

    def test_print_healthy_report(self):
        """Test printing a healthy report."""
        from src.cli.health_check import print_health_report
        from rich.console import Console

        result = create_health_result(passed=True)
        console = Console(force_terminal=True, no_color=True)
        # Should not raise
        print_health_report(result, console, verbose=False)

    def test_print_unhealthy_report(self):
        """Test printing an unhealthy report."""
        from src.cli.health_check import print_health_report
        from rich.console import Console

        result = create_health_result(passed=False, with_alerts=True)
        console = Console(force_terminal=True, no_color=True)
        # Should not raise
        print_health_report(result, console, verbose=False)

    def test_print_report_verbose(self):
        """Test printing report in verbose mode."""
        from src.cli.health_check import print_health_report
        from rich.console import Console

        result = create_health_result(passed=True)
        console = Console(force_terminal=True, no_color=True)
        # Should not raise
        print_health_report(result, console, verbose=True)

    def test_print_report_with_alerts(self):
        """Test printing report with alerts."""
        from src.cli.health_check import print_health_report
        from rich.console import Console

        result = create_health_result(passed=False, with_alerts=True)
        console = Console(force_terminal=True, no_color=True)
        # Should not raise
        print_health_report(result, console, verbose=False)

    def test_print_report_with_queue_stats_verbose(self):
        """Test printing report with queue statistics in verbose mode."""
        from src.cli.health_check import print_health_report
        from rich.console import Console

        result = create_health_result(passed=True, with_stats=True)
        console = Console(force_terminal=True, no_color=True)
        # Should not raise - this tests the queue_by_status table
        print_health_report(result, console, verbose=True)

    def test_print_report_high_failure_rate(self):
        """Test printing report with high failure rate."""
        from src.cli.health_check import print_health_report
        from rich.console import Console

        result = create_health_result(passed=True, with_stats=True)
        # Modify stats to have high failure rate
        result.stats.captures_received_24h = 10
        result.stats.captures_failed_24h = 5  # 50% failure rate

        console = Console(force_terminal=True, no_color=True)
        print_health_report(result, console, verbose=False)

    def test_print_report_no_stats(self):
        """Test printing report without stats."""
        from src.cli.health_check import print_health_report
        from rich.console import Console

        result = create_health_result(passed=True, with_stats=False)
        console = Console(force_terminal=True, no_color=True)
        print_health_report(result, console, verbose=False)


# ============================================================================
# Run Health Check Tests
# ============================================================================


class TestRunHealthCheck:
    """Tests for run_health_check function."""

    @pytest.mark.asyncio
    async def test_run_health_check_success(self, mock_settings, temp_dir):
        """Test running health check successfully."""
        from src.cli.health_check import run_health_check

        mock_settings.paths.database = temp_dir / "test.db"
        mock_health_result = create_health_result(passed=True)

        mock_db = AsyncMock()
        mock_checker = AsyncMock()
        mock_checker.run_all_checks.return_value = mock_health_result

        with patch("src.cli.health_check.get_settings", return_value=mock_settings), \
             patch("src.cli.health_check.reload_settings"), \
             patch("src.cli.health_check.Database", return_value=mock_db), \
             patch("src.cli.health_check.HealthChecker", return_value=mock_checker):
            result = await run_health_check(notify=False, verbose=False)

        assert result is not None
        mock_checker.run_all_checks.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_health_check_with_notification(self, mock_settings, temp_dir):
        """Test running health check with notification enabled."""
        from src.cli.health_check import run_health_check

        mock_settings.paths.database = temp_dir / "test.db"
        mock_health_result = create_health_result(passed=True)

        mock_db = AsyncMock()
        mock_checker = AsyncMock()
        mock_checker.run_all_checks.return_value = mock_health_result
        mock_pushover = AsyncMock()

        with patch("src.cli.health_check.get_settings", return_value=mock_settings), \
             patch("src.cli.health_check.reload_settings"), \
             patch("src.cli.health_check.Database", return_value=mock_db), \
             patch("src.cli.health_check.HealthChecker", return_value=mock_checker), \
             patch("src.cli.health_check.PushoverService", return_value=mock_pushover):
            result = await run_health_check(notify=True, verbose=False)

        assert result is not None
        mock_checker.send_health_notification.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_health_check_no_pushover_config(self, mock_settings, temp_dir):
        """Test health check when Pushover is not configured."""
        from src.cli.health_check import run_health_check

        mock_settings.paths.database = temp_dir / "test.db"
        mock_settings.pushover_api_token = None
        mock_settings.pushover_user_key = None
        mock_health_result = create_health_result(passed=True)

        mock_db = AsyncMock()
        mock_checker = AsyncMock()
        mock_checker.run_all_checks.return_value = mock_health_result

        with patch("src.cli.health_check.get_settings", return_value=mock_settings), \
             patch("src.cli.health_check.reload_settings"), \
             patch("src.cli.health_check.Database", return_value=mock_db), \
             patch("src.cli.health_check.HealthChecker", return_value=mock_checker):
            result = await run_health_check(notify=True, verbose=False)

        assert result is not None
        # Should not send notification when Pushover not configured
        mock_checker.send_health_notification.assert_not_called()


# ============================================================================
# CLI Tests
# ============================================================================


class TestHealthCheckCLI:
    """Tests for health_check CLI command."""

    def test_cli_help(self, cli_runner: CliRunner):
        """Test CLI help output."""
        from src.cli.health_check import health_check_cli

        result = cli_runner.invoke(health_check_cli, ["--help"])

        assert result.exit_code == 0
        assert "Run Voice Capture health checks" in result.output
        assert "--notify" in result.output
        assert "--verbose" in result.output

    def test_cli_no_notify(self, cli_runner: CliRunner, mock_settings, temp_dir):
        """Test CLI with --no-notify flag."""
        from src.cli.health_check import health_check_cli

        mock_settings.paths.database = temp_dir / "test.db"
        mock_health_result = create_health_result(passed=True)

        mock_db = AsyncMock()
        mock_checker = AsyncMock()
        mock_checker.run_all_checks.return_value = mock_health_result

        with patch("src.cli.health_check.get_settings", return_value=mock_settings), \
             patch("src.cli.health_check.reload_settings"), \
             patch("src.cli.health_check.Database", return_value=mock_db), \
             patch("src.cli.health_check.HealthChecker", return_value=mock_checker):
            result = cli_runner.invoke(health_check_cli, ["--no-notify"])

        assert result.exit_code == 0

    def test_cli_verbose(self, cli_runner: CliRunner, mock_settings, temp_dir):
        """Test CLI with --verbose flag."""
        from src.cli.health_check import health_check_cli

        mock_settings.paths.database = temp_dir / "test.db"
        mock_health_result = create_health_result(passed=True)

        mock_db = AsyncMock()
        mock_checker = AsyncMock()
        mock_checker.run_all_checks.return_value = mock_health_result

        with patch("src.cli.health_check.get_settings", return_value=mock_settings), \
             patch("src.cli.health_check.reload_settings"), \
             patch("src.cli.health_check.Database", return_value=mock_db), \
             patch("src.cli.health_check.HealthChecker", return_value=mock_checker):
            result = cli_runner.invoke(health_check_cli, ["--no-notify", "--verbose"])

        assert result.exit_code == 0

    def test_cli_exit_code_on_failure(self, cli_runner: CliRunner, mock_settings, temp_dir):
        """Test CLI exits with code 1 on health check failure."""
        from src.cli.health_check import health_check_cli

        mock_settings.paths.database = temp_dir / "test.db"
        mock_health_result = create_health_result(passed=False)

        mock_db = AsyncMock()
        mock_checker = AsyncMock()
        mock_checker.run_all_checks.return_value = mock_health_result

        with patch("src.cli.health_check.get_settings", return_value=mock_settings), \
             patch("src.cli.health_check.reload_settings"), \
             patch("src.cli.health_check.Database", return_value=mock_db), \
             patch("src.cli.health_check.HealthChecker", return_value=mock_checker):
            result = cli_runner.invoke(health_check_cli, ["--no-notify"])

        assert result.exit_code == 1

    def test_cli_handles_exception(self, cli_runner: CliRunner):
        """Test CLI handles exceptions gracefully."""
        from src.cli.health_check import health_check_cli

        with patch("src.cli.health_check.reload_settings"), \
             patch("src.cli.health_check.get_settings", side_effect=Exception("Config error")):
            result = cli_runner.invoke(health_check_cli, ["--no-notify"])

        assert result.exit_code == 1
        assert "failed" in result.output.lower()
