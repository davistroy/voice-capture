"""Tests for verify_config CLI command.

Tests the configuration verification functionality including
environment variable checks, directory permissions, and API connectivity.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from src.cli.verify_config import (
    CheckResult,
    CheckStatus,
    VerificationReport,
    _check_directory,
    _check_directories,
    _check_optional_env_vars,
    _check_required_env_vars,
    _test_notion_api,
    _test_whisper_api,
    print_report,
    verify_config_cli,
)


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
    settings.openai_api_key = "test-openai-key-1234567890"
    settings.anthropic_api_key = "test-anthropic-key-1234567890"
    settings.notion_api_key = "test-notion-key-1234567890"
    settings.notion_voice_captures_db_id = "test-db-id-1234567890"
    settings.pushover_api_token = "test-pushover-token"
    settings.pushover_user_key = "test-pushover-user"
    settings.notion_weekly_summaries_db_id = "test-weekly-db"

    # Set up paths
    settings.paths = MagicMock()
    settings.paths.inbox = temp_dir / "inbox"
    settings.paths.processing = temp_dir / "processing"
    settings.paths.failed = temp_dir / "failed"
    settings.paths.database = temp_dir / "data" / "voice_capture.db"
    settings.paths.logs = temp_dir / "logs"
    settings.paths.templates = temp_dir / "templates"

    # Create directories
    for path in [settings.paths.inbox, settings.paths.processing,
                 settings.paths.failed, settings.paths.logs,
                 settings.paths.templates]:
        path.mkdir(parents=True, exist_ok=True)
    settings.paths.database.parent.mkdir(parents=True, exist_ok=True)

    return settings


# ============================================================================
# CheckResult Tests
# ============================================================================


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    def test_check_result_creation(self):
        """Test creating a check result."""
        result = CheckResult(
            name="Test Check",
            status=CheckStatus.PASS,
            message="Check passed",
            details="Additional info",
        )

        assert result.name == "Test Check"
        assert result.status == CheckStatus.PASS
        assert result.message == "Check passed"
        assert result.details == "Additional info"

    def test_check_result_without_details(self):
        """Test creating a check result without details."""
        result = CheckResult(
            name="Test",
            status=CheckStatus.FAIL,
            message="Failed",
        )

        assert result.details is None


# ============================================================================
# VerificationReport Tests
# ============================================================================


class TestVerificationReport:
    """Tests for VerificationReport dataclass."""

    def test_empty_report(self):
        """Test empty verification report."""
        report = VerificationReport()

        assert len(report.checks) == 0
        assert report.passed == 0
        assert report.failed == 0
        assert report.warnings == 0
        assert report.skipped == 0
        assert report.all_passed is True

    def test_add_check_pass(self):
        """Test adding a passed check."""
        report = VerificationReport()
        report.add_check(CheckResult("Test", CheckStatus.PASS, "OK"))

        assert report.passed == 1
        assert report.failed == 0
        assert report.all_passed is True

    def test_add_check_fail(self):
        """Test adding a failed check."""
        report = VerificationReport()
        report.add_check(CheckResult("Test", CheckStatus.FAIL, "Failed"))

        assert report.failed == 1
        assert report.passed == 0
        assert report.all_passed is False

    def test_add_check_warn(self):
        """Test adding a warning check."""
        report = VerificationReport()
        report.add_check(CheckResult("Test", CheckStatus.WARN, "Warning"))

        assert report.warnings == 1
        assert report.all_passed is True  # Warnings don't fail the report

    def test_add_check_skip(self):
        """Test adding a skipped check."""
        report = VerificationReport()
        report.add_check(CheckResult("Test", CheckStatus.SKIP, "Skipped"))

        assert report.skipped == 1
        assert report.all_passed is True

    def test_mixed_results(self):
        """Test report with mixed results."""
        report = VerificationReport()
        report.add_check(CheckResult("Test1", CheckStatus.PASS, "OK"))
        report.add_check(CheckResult("Test2", CheckStatus.PASS, "OK"))
        report.add_check(CheckResult("Test3", CheckStatus.WARN, "Warning"))
        report.add_check(CheckResult("Test4", CheckStatus.SKIP, "Skipped"))

        assert report.passed == 2
        assert report.warnings == 1
        assert report.skipped == 1
        assert report.failed == 0
        assert report.all_passed is True
        assert len(report.checks) == 4


# ============================================================================
# Directory Check Tests
# ============================================================================


class TestDirectoryCheck:
    """Tests for directory permission checking."""

    def test_check_existing_directory_read_write(self, temp_dir: Path):
        """Test checking an existing directory with read/write access."""
        result = _check_directory("Test Dir", temp_dir, True, True)

        assert result.status == CheckStatus.PASS
        assert "read" in result.message
        assert "write" in result.message

    def test_check_nonexistent_directory_creates(self, temp_dir: Path):
        """Test that nonexistent directory is created."""
        new_dir = temp_dir / "new_directory"
        assert not new_dir.exists()

        result = _check_directory("New Dir", new_dir, True, True)

        assert result.status == CheckStatus.PASS
        assert "Created" in result.message
        assert new_dir.exists()

    def test_check_directory_read_only(self, temp_dir: Path):
        """Test checking a directory for read-only access."""
        result = _check_directory("Read Only", temp_dir, True, False)

        assert result.status == CheckStatus.PASS
        assert "read" in result.message


# ============================================================================
# Environment Variable Check Tests
# ============================================================================


class TestEnvVarChecks:
    """Tests for environment variable checking."""

    @pytest.mark.asyncio
    async def test_check_required_env_vars_all_set(self, mock_settings):
        """Test checking required env vars when all are set."""
        report = VerificationReport()
        await _check_required_env_vars(mock_settings, report)

        # Should have 4 required checks
        assert len(report.checks) == 4
        assert all(c.status == CheckStatus.PASS for c in report.checks)

    @pytest.mark.asyncio
    async def test_check_required_env_vars_missing(self, mock_settings):
        """Test checking required env vars when some are missing."""
        mock_settings.openai_api_key = ""
        mock_settings.notion_api_key = None

        report = VerificationReport()
        await _check_required_env_vars(mock_settings, report)

        failed_checks = [c for c in report.checks if c.status == CheckStatus.FAIL]
        assert len(failed_checks) >= 2

    @pytest.mark.asyncio
    async def test_check_optional_env_vars_all_set(self, mock_settings):
        """Test checking optional env vars when all are set."""
        report = VerificationReport()
        await _check_optional_env_vars(mock_settings, report)

        # Should have 3 optional checks
        assert len(report.checks) == 3
        assert all(c.status == CheckStatus.PASS for c in report.checks)

    @pytest.mark.asyncio
    async def test_check_optional_env_vars_missing(self, mock_settings):
        """Test checking optional env vars when some are missing."""
        mock_settings.pushover_api_token = ""
        mock_settings.pushover_user_key = None

        report = VerificationReport()
        await _check_optional_env_vars(mock_settings, report)

        # Missing optional vars should be warnings, not failures
        warn_checks = [c for c in report.checks if c.status == CheckStatus.WARN]
        assert len(warn_checks) >= 2

    @pytest.mark.asyncio
    async def test_short_api_key_masked_correctly(self, mock_settings):
        """Test that short API keys are masked with ***."""
        mock_settings.openai_api_key = "short"  # Less than 12 chars

        report = VerificationReport()
        await _check_required_env_vars(mock_settings, report)

        openai_check = next(c for c in report.checks if "OPENAI" in c.name)
        assert "***" in openai_check.message


# ============================================================================
# API Connectivity Check Tests
# ============================================================================


class TestApiConnectivityChecks:
    """Tests for API connectivity checking."""

    @pytest.mark.asyncio
    async def test_whisper_api_no_key(self):
        """Test Whisper API check with no API key."""
        result = await _test_whisper_api("", False)

        assert result.status == CheckStatus.SKIP
        assert "not set" in result.message

    @pytest.mark.asyncio
    async def test_notion_api_no_key(self):
        """Test Notion API check with no API key."""
        result = await _test_notion_api("", "test-db", False)

        assert result.status == CheckStatus.SKIP
        assert "not set" in result.message

    @pytest.mark.asyncio
    async def test_notion_api_no_db_id(self):
        """Test Notion API check with no database ID."""
        result = await _test_notion_api("test-key", "", False)

        assert result.status == CheckStatus.SKIP
        assert "not set" in result.message


# ============================================================================
# Directory Checks Tests
# ============================================================================


class TestCheckDirectories:
    """Tests for _check_directories function."""

    @pytest.mark.asyncio
    async def test_check_directories_all_exist(self, mock_settings):
        """Test directory checks when all directories exist."""
        report = VerificationReport()
        await _check_directories(mock_settings, report)

        # Should have 6 directory checks
        assert len(report.checks) == 6
        assert all(c.status == CheckStatus.PASS for c in report.checks)


# ============================================================================
# Print Report Tests
# ============================================================================


class TestPrintReport:
    """Tests for print_report function."""

    def test_print_report_all_passed(self, capsys):
        """Test printing report when all checks pass."""
        from rich.console import Console

        console = Console(force_terminal=True, no_color=True)
        report = VerificationReport()
        report.add_check(CheckResult("Test1", CheckStatus.PASS, "OK"))
        report.add_check(CheckResult("Test2", CheckStatus.PASS, "OK"))

        print_report(report, console)
        # No assertion needed - just verify it doesn't raise

    def test_print_report_with_failures(self, capsys):
        """Test printing report with failures."""
        from rich.console import Console

        console = Console(force_terminal=True, no_color=True)
        report = VerificationReport()
        report.add_check(CheckResult("Test1", CheckStatus.PASS, "OK"))
        report.add_check(CheckResult("Test2", CheckStatus.FAIL, "Failed"))

        print_report(report, console)
        # No assertion needed - just verify it doesn't raise

    def test_print_report_with_all_statuses(self, capsys):
        """Test printing report with all status types."""
        from rich.console import Console

        console = Console(force_terminal=True, no_color=True)
        report = VerificationReport()
        report.add_check(CheckResult("Pass", CheckStatus.PASS, "OK"))
        report.add_check(CheckResult("Fail", CheckStatus.FAIL, "Failed"))
        report.add_check(CheckResult("Warn", CheckStatus.WARN, "Warning"))
        report.add_check(CheckResult("Skip", CheckStatus.SKIP, "Skipped"))

        print_report(report, console)
        # No assertion needed - just verify it doesn't raise


# ============================================================================
# CLI Tests
# ============================================================================


class TestVerifyConfigCLI:
    """Tests for verify_config CLI command."""

    def test_cli_help(self, cli_runner: CliRunner):
        """Test CLI help output."""
        result = cli_runner.invoke(verify_config_cli, ["--help"])

        assert result.exit_code == 0
        assert "Verify Voice Capture configuration" in result.output
        assert "--test-apis" in result.output
        assert "--verbose" in result.output

    def test_cli_no_test_apis(self, cli_runner: CliRunner, mock_settings):
        """Test CLI with --no-test-apis flag."""
        with patch("src.config.settings.get_settings", return_value=mock_settings), \
             patch("src.config.settings.reload_settings"):
            result = cli_runner.invoke(verify_config_cli, ["--no-test-apis"])

        # Should succeed (the mock patches the imported functions)
        assert result.exit_code == 0


# ============================================================================
# Check Status Enum Tests
# ============================================================================


class TestCheckStatus:
    """Tests for CheckStatus enum."""

    def test_all_status_values(self):
        """Test all status values exist."""
        assert CheckStatus.PASS.value == "pass"
        assert CheckStatus.FAIL.value == "fail"
        assert CheckStatus.WARN.value == "warn"
        assert CheckStatus.SKIP.value == "skip"
