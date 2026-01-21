"""Health check CLI command for Voice Capture.

Runs comprehensive health checks including API connectivity,
directory permissions, and processing statistics. Sends notifications
via Pushover.

Usage:
    python -m src.cli.health_check
    python -m src.cli.health_check --no-notify
    python -m src.cli.health_check --verbose

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

import asyncio
import sys
from datetime import datetime

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config.settings import get_settings, reload_settings
from src.db.database import Database
from src.health.checker import CheckStatus, HealthCheckResult, HealthChecker
from src.notifications.pushover import PushoverService


async def run_health_check(
    notify: bool = True,
    verbose: bool = False,
) -> HealthCheckResult:
    """Run health check and optionally send notification.

    Args:
        notify: Whether to send Pushover notification.
        verbose: Include additional details in output.

    Returns:
        HealthCheckResult with all check results.
    """
    # Reload settings to get fresh values
    reload_settings()
    settings = get_settings()

    # Initialize database
    db = Database(settings.paths.database)
    await db.initialize()

    try:
        # Initialize Pushover if configured and notifications enabled
        pushover = None
        if notify and settings.pushover_api_token and settings.pushover_user_key:
            pushover = PushoverService(
                api_token=settings.pushover_api_token,
                user_key=settings.pushover_user_key,
            )

        # Create health checker and run checks
        checker = HealthChecker(settings, db, pushover)
        result = await checker.run_all_checks()

        # Send notification if enabled
        if notify and pushover:
            await checker.send_health_notification(result)

        return result

    finally:
        await db.close()


def print_health_report(result: HealthCheckResult, console: Console, verbose: bool = False) -> None:
    """Print health check report to console with rich formatting.

    Args:
        result: The health check result to print.
        console: Rich console for output.
        verbose: Include additional details.
    """
    # Create checks table
    table = Table(title="Health Checks", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Message")
    if verbose:
        table.add_column("Duration", justify="right")
        table.add_column("Details", style="dim")

    # Status display mapping
    status_display = {
        CheckStatus.PASS: "[green]PASS[/green]",
        CheckStatus.FAIL: "[red]FAIL[/red]",
        CheckStatus.WARN: "[yellow]WARN[/yellow]",
        CheckStatus.SKIP: "[dim]SKIP[/dim]",
    }

    for check in result.checks:
        row = [
            check.name,
            status_display[check.status],
            check.message,
        ]
        if verbose:
            duration = f"{check.duration_ms:.0f}ms" if check.duration_ms else "-"
            row.append(duration)
            row.append(check.details or "")
        table.add_row(*row)

    console.print(table)
    console.print()

    # Print statistics if available
    if result.stats:
        stats_table = Table(title="Processing Statistics (24h)", show_header=True)
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", justify="right")

        stats_table.add_row("Captures Received", str(result.stats.captures_received_24h))
        stats_table.add_row("Captures Completed", str(result.stats.captures_completed_24h))
        stats_table.add_row("Captures Failed", str(result.stats.captures_failed_24h))
        stats_table.add_row("Current Queue Depth", str(result.stats.current_queue_depth))

        if result.stats.failure_rate > 0:
            failure_pct = result.stats.failure_rate * 100
            color = "red" if failure_pct > 20 else "yellow" if failure_pct > 10 else "green"
            stats_table.add_row("Failure Rate", f"[{color}]{failure_pct:.1f}%[/{color}]")

        console.print(stats_table)
        console.print()

        # Queue breakdown if verbose
        if verbose and result.stats.queue_by_status:
            queue_table = Table(title="Queue by Status", show_header=True)
            queue_table.add_column("Status", style="cyan")
            queue_table.add_column("Count", justify="right")

            for status, count in sorted(result.stats.queue_by_status.items()):
                queue_table.add_row(status, str(count))

            console.print(queue_table)
            console.print()

    # Print alerts if any
    if result.alerts:
        alert_lines = []
        for alert in result.alerts:
            if alert.startswith("HIGH:"):
                alert_lines.append(f"[red]{alert}[/red]")
            else:
                alert_lines.append(f"[yellow]{alert}[/yellow]")

        console.print(Panel(
            "\n".join(alert_lines),
            title="Alerts",
            border_style="red" if any(a.startswith("HIGH:") for a in result.alerts) else "yellow",
        ))
        console.print()

    # Summary panel
    summary_parts = []
    if result.passed > 0:
        summary_parts.append(f"[green]{result.passed} passed[/green]")
    if result.failed > 0:
        summary_parts.append(f"[red]{result.failed} failed[/red]")
    if result.warnings > 0:
        summary_parts.append(f"[yellow]{result.warnings} warnings[/yellow]")
    if result.skipped > 0:
        summary_parts.append(f"[dim]{result.skipped} skipped[/dim]")

    summary = " | ".join(summary_parts)

    timestamp = result.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    if result.is_healthy:
        console.print(Panel(
            f"{summary}\n\n[bold green]System is healthy[/bold green]\n\nChecked at: {timestamp}",
            title="Summary",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"{summary}\n\n[bold red]System has issues - check failed items[/bold red]\n\nChecked at: {timestamp}",
            title="Summary",
            border_style="red",
        ))


@click.command()
@click.option(
    "--notify/--no-notify",
    default=True,
    help="Send Pushover notification with results",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Show additional details",
)
def health_check_cli(notify: bool, verbose: bool) -> None:
    """Run Voice Capture health checks.

    Checks API connectivity, directory permissions, and processing
    statistics. Optionally sends notification via Pushover.

    Exit codes:
        0 - All checks passed
        1 - One or more checks failed
    """
    console = Console()

    console.print("\n[bold]Voice Capture Health Check[/bold]\n")

    try:
        # Run health check
        result = asyncio.run(run_health_check(notify=notify, verbose=verbose))

        # Print report
        print_health_report(result, console, verbose)

        # Notification status
        if notify:
            if result.alerts:
                console.print("[dim]Notification sent via Pushover[/dim]\n")
            else:
                console.print("[dim]Daily summary sent via Pushover[/dim]\n")

        # Exit with appropriate code
        sys.exit(0 if result.is_healthy else 1)

    except Exception as e:
        console.print(f"\n[red]Health check failed: {e}[/red]\n")
        sys.exit(1)


# Entry point for `python -m src.cli.health_check`
if __name__ == "__main__":
    health_check_cli()
