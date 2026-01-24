"""Configuration verification CLI command.

Verifies that all required configuration is present and valid,
tests API connectivity, and checks directory permissions.

Usage:
    python -m src.cli.verify_config

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

import asyncio
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


class CheckStatus(Enum):
    """Status of a verification check."""
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Result of a single verification check.

    Attributes:
        name: Name of the check.
        status: Pass, fail, warn, or skip.
        message: Description of result.
        details: Optional additional details.
    """
    name: str
    status: CheckStatus
    message: str
    details: Optional[str] = None


@dataclass
class VerificationReport:
    """Complete verification report.

    Attributes:
        checks: List of individual check results.
        passed: Number of passed checks.
        failed: Number of failed checks.
        warnings: Number of warning checks.
        skipped: Number of skipped checks.
    """
    checks: list[CheckResult] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    skipped: int = 0

    def add_check(self, result: CheckResult) -> None:
        """Add a check result to the report."""
        self.checks.append(result)
        if result.status == CheckStatus.PASS:
            self.passed += 1
        elif result.status == CheckStatus.FAIL:
            self.failed += 1
        elif result.status == CheckStatus.WARN:
            self.warnings += 1
        elif result.status == CheckStatus.SKIP:
            self.skipped += 1

    @property
    def all_passed(self) -> bool:
        """True if no checks failed."""
        return self.failed == 0


async def verify_config(test_apis: bool = True, verbose: bool = False) -> VerificationReport:
    """Verify configuration and optionally test API connectivity.

    Checks:
    1. Required environment variables
    2. Optional environment variables
    3. Directory permissions (read/write)
    4. API connectivity (Whisper, Notion) if test_apis=True

    Args:
        test_apis: Whether to test API connectivity (requires valid keys).
        verbose: Include additional details in output.

    Returns:
        VerificationReport with all check results.
    """
    from src.config.settings import get_settings, reload_settings

    report = VerificationReport()

    # Reload settings to get fresh values
    reload_settings()

    try:
        settings = get_settings()
    except Exception as e:
        report.add_check(CheckResult(
            name="Settings Load",
            status=CheckStatus.FAIL,
            message=f"Failed to load settings: {e}",
        ))
        return report

    report.add_check(CheckResult(
        name="Settings Load",
        status=CheckStatus.PASS,
        message="Configuration loaded successfully",
    ))

    # Check required environment variables
    await _check_required_env_vars(settings, report)

    # Check optional environment variables
    await _check_optional_env_vars(settings, report)

    # Check directory permissions
    await _check_directories(settings, report)

    # Test API connectivity
    if test_apis:
        await _check_api_connectivity(settings, report, verbose)
    else:
        report.add_check(CheckResult(
            name="API Connectivity",
            status=CheckStatus.SKIP,
            message="API connectivity tests skipped",
        ))

    return report


async def _check_required_env_vars(settings, report: VerificationReport) -> None:
    """Check required environment variables."""
    required_vars = [
        ("OPENAI_API_KEY", settings.openai_api_key, "Required for Whisper transcription"),
        ("ANTHROPIC_API_KEY", settings.anthropic_api_key, "Required for Claude classification (Phase 2)"),
        ("NOTION_API_KEY", settings.notion_api_key, "Required for Notion integration"),
        ("NOTION_VOICE_CAPTURES_DB_ID", settings.notion_voice_captures_db_id, "Required for Notion database"),
    ]

    for var_name, value, description in required_vars:
        if value and len(value) > 0:
            # Mask the value for display
            masked = value[:4] + "..." + value[-4:] if len(value) > 12 else "***"
            report.add_check(CheckResult(
                name=var_name,
                status=CheckStatus.PASS,
                message=f"Set ({masked})",
                details=description,
            ))
        else:
            report.add_check(CheckResult(
                name=var_name,
                status=CheckStatus.FAIL,
                message="Not set or empty",
                details=description,
            ))


async def _check_optional_env_vars(settings, report: VerificationReport) -> None:
    """Check optional environment variables."""
    optional_vars = [
        ("PUSHOVER_API_TOKEN", settings.pushover_api_token, "For push notifications (Phase 3)"),
        ("PUSHOVER_USER_KEY", settings.pushover_user_key, "For push notifications (Phase 3)"),
        ("NOTION_WEEKLY_SUMMARIES_DB_ID", settings.notion_weekly_summaries_db_id, "For weekly synthesis (Phase 4)"),
    ]

    for var_name, value, description in optional_vars:
        if value and len(value) > 0:
            masked = value[:4] + "..." + value[-4:] if len(value) > 12 else "***"
            report.add_check(CheckResult(
                name=var_name,
                status=CheckStatus.PASS,
                message=f"Set ({masked})",
                details=description,
            ))
        else:
            report.add_check(CheckResult(
                name=var_name,
                status=CheckStatus.WARN,
                message="Not set (optional)",
                details=description,
            ))


async def _check_directories(settings, report: VerificationReport) -> None:
    """Check directory permissions."""
    directories = [
        ("Inbox", settings.paths.inbox, True, True),  # read, write
        ("Processing", settings.paths.processing, True, True),
        ("Failed", settings.paths.failed, True, True),
        ("Database Dir", settings.paths.database.parent, True, True),
        ("Logs", settings.paths.logs, True, True),
        ("Templates", settings.paths.templates, True, False),  # read only
    ]

    for name, path, need_read, need_write in directories:
        result = _check_directory(name, path, need_read, need_write)
        report.add_check(result)


def _check_directory(
    name: str,
    path: Path,
    need_read: bool,
    need_write: bool,
) -> CheckResult:
    """Check a single directory for required permissions.

    Args:
        name: Display name for the directory.
        path: Path to check.
        need_read: Whether read permission is required.
        need_write: Whether write permission is required.

    Returns:
        CheckResult for the directory check.
    """
    try:
        # Check if path exists
        if not path.exists():
            # Try to create it
            try:
                path.mkdir(parents=True, exist_ok=True)
                return CheckResult(
                    name=f"Directory: {name}",
                    status=CheckStatus.PASS,
                    message=f"Created: {path}",
                )
            except Exception as e:
                return CheckResult(
                    name=f"Directory: {name}",
                    status=CheckStatus.FAIL,
                    message=f"Cannot create: {path}",
                    details=str(e),
                )

        # Check permissions
        can_read = os.access(path, os.R_OK)
        can_write = os.access(path, os.W_OK)

        if need_read and not can_read:
            return CheckResult(
                name=f"Directory: {name}",
                status=CheckStatus.FAIL,
                message=f"No read permission: {path}",
            )

        if need_write and not can_write:
            return CheckResult(
                name=f"Directory: {name}",
                status=CheckStatus.FAIL,
                message=f"No write permission: {path}",
            )

        permissions = []
        if can_read:
            permissions.append("read")
        if can_write:
            permissions.append("write")

        return CheckResult(
            name=f"Directory: {name}",
            status=CheckStatus.PASS,
            message=f"OK ({', '.join(permissions)}): {path}",
        )

    except Exception as e:
        return CheckResult(
            name=f"Directory: {name}",
            status=CheckStatus.FAIL,
            message=f"Error checking: {path}",
            details=str(e),
        )


async def _check_api_connectivity(
    settings,
    report: VerificationReport,
    verbose: bool,
) -> None:
    """Test API connectivity.

    Tests:
    - OpenAI Whisper API (models list)
    - Notion API (database query)
    """
    # Test OpenAI/Whisper API
    whisper_result = await _test_whisper_api(settings.openai_api_key, verbose)
    report.add_check(whisper_result)

    # Test Notion API
    notion_result = await _test_notion_api(
        settings.notion_api_key,
        settings.notion_voice_captures_db_id,
        verbose,
    )
    report.add_check(notion_result)


async def _test_whisper_api(api_key: str, verbose: bool) -> CheckResult:
    """Test OpenAI Whisper API connectivity.

    Makes a lightweight call to verify the API key works.

    Args:
        api_key: OpenAI API key.
        verbose: Include response details.

    Returns:
        CheckResult for the API test.
    """
    if not api_key:
        return CheckResult(
            name="Whisper API",
            status=CheckStatus.SKIP,
            message="Skipped - API key not set",
        )

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)

        # Use models.list() as a lightweight connectivity check
        # This verifies the API key without incurring transcription costs
        models = await client.models.list()

        # Check if whisper model is available
        model_ids = [m.id for m in models.data]
        has_whisper = any("whisper" in m.lower() for m in model_ids)

        if has_whisper:
            return CheckResult(
                name="Whisper API",
                status=CheckStatus.PASS,
                message="Connected - Whisper model available",
                details=f"Found {len(model_ids)} models" if verbose else None,
            )
        else:
            return CheckResult(
                name="Whisper API",
                status=CheckStatus.WARN,
                message="Connected but Whisper model not found",
                details="Check API key permissions",
            )

    except Exception as e:
        error_msg = str(e)
        # Truncate long error messages
        if len(error_msg) > 100:
            error_msg = error_msg[:100] + "..."

        return CheckResult(
            name="Whisper API",
            status=CheckStatus.FAIL,
            message="Connection failed",
            details=error_msg,
        )


async def _test_notion_api(
    api_key: str,
    database_id: str,
    verbose: bool,
) -> CheckResult:
    """Test Notion API connectivity.

    Queries the database to verify access.

    Args:
        api_key: Notion API key.
        database_id: Voice Captures database ID.
        verbose: Include response details.

    Returns:
        CheckResult for the API test.
    """
    if not api_key:
        return CheckResult(
            name="Notion API",
            status=CheckStatus.SKIP,
            message="Skipped - API key not set",
        )

    if not database_id:
        return CheckResult(
            name="Notion API",
            status=CheckStatus.SKIP,
            message="Skipped - Database ID not set",
        )

    try:
        from notion_client import AsyncClient

        client = AsyncClient(auth=api_key)

        # Retrieve database metadata to verify access
        # Using databases.retrieve() instead of query() for compatibility
        # with notion-client 2.7.0+ where query() moved to data_sources
        response = await client.databases.retrieve(
            database_id=database_id,
        )

        # Check response - retrieve returns database object with id
        if "id" in response:
            db_title = "Unknown"
            if response.get("title"):
                title_parts = response["title"]
                if title_parts and len(title_parts) > 0:
                    db_title = title_parts[0].get("plain_text", "Unknown")
            return CheckResult(
                name="Notion API",
                status=CheckStatus.PASS,
                message=f"Connected - Database accessible",
                details=f"Database: {db_title}" if verbose else None,
            )
        else:
            return CheckResult(
                name="Notion API",
                status=CheckStatus.WARN,
                message="Connected but unexpected response",
            )

    except Exception as e:
        error_msg = str(e)
        # Truncate long error messages
        if len(error_msg) > 100:
            error_msg = error_msg[:100] + "..."

        return CheckResult(
            name="Notion API",
            status=CheckStatus.FAIL,
            message="Connection failed",
            details=error_msg,
        )


def print_report(report: VerificationReport, console: Console) -> None:
    """Print verification report to console with rich formatting.

    Args:
        report: The verification report to print.
        console: Rich console for output.
    """
    # Create table
    table = Table(title="Configuration Verification", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Message")
    table.add_column("Details", style="dim")

    # Status emoji mapping
    status_display = {
        CheckStatus.PASS: "[green]PASS[/green]",
        CheckStatus.FAIL: "[red]FAIL[/red]",
        CheckStatus.WARN: "[yellow]WARN[/yellow]",
        CheckStatus.SKIP: "[dim]SKIP[/dim]",
    }

    for check in report.checks:
        table.add_row(
            check.name,
            status_display[check.status],
            check.message,
            check.details or "",
        )

    console.print(table)

    # Summary
    summary_parts = []
    if report.passed > 0:
        summary_parts.append(f"[green]{report.passed} passed[/green]")
    if report.failed > 0:
        summary_parts.append(f"[red]{report.failed} failed[/red]")
    if report.warnings > 0:
        summary_parts.append(f"[yellow]{report.warnings} warnings[/yellow]")
    if report.skipped > 0:
        summary_parts.append(f"[dim]{report.skipped} skipped[/dim]")

    summary = " | ".join(summary_parts)

    if report.all_passed:
        console.print(Panel(
            f"{summary}\n\n[bold green]All required checks passed![/bold green]",
            title="Summary",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"{summary}\n\n[bold red]Configuration issues detected. Please fix failed checks.[/bold red]",
            title="Summary",
            border_style="red",
        ))


@click.command()
@click.option(
    "--test-apis/--no-test-apis",
    default=True,
    help="Test API connectivity (requires valid keys)",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Show additional details",
)
def verify_config_cli(test_apis: bool, verbose: bool) -> None:
    """Verify Voice Capture configuration.

    Checks all required environment variables, directory permissions,
    and optionally tests API connectivity.

    Exit codes:
        0 - All required checks passed
        1 - One or more required checks failed
    """
    console = Console()

    console.print("\n[bold]Voice Capture Configuration Verification[/bold]\n")

    # Run verification
    report = asyncio.run(verify_config(test_apis=test_apis, verbose=verbose))

    # Print report
    print_report(report, console)

    # Exit with appropriate code
    sys.exit(0 if report.all_passed else 1)


# Entry point for `python -m src.cli.verify_config`
if __name__ == "__main__":
    verify_config_cli()
