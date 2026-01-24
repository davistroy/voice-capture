"""Queue status CLI command for Voice Capture.

Shows the current processing queue status including pending, processing,
and failed items with their error messages.

Usage:
    python -m src.cli.queue_status
    python -m src.cli.queue_status --verbose
    python -m src.cli.queue_status --failed
    python -m src.cli.queue_status --http

Exit codes:
    0 - Status retrieved successfully
    1 - Error retrieving status
"""

import asyncio
import sys
from datetime import datetime
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config.settings import get_settings, reload_settings
from src.db.database import Database


async def get_queue_status(db: Database) -> dict:
    """Get current queue status.

    Args:
        db: Database instance.

    Returns:
        Dict with queue counts and details.
    """
    # Get counts by status
    queue_depth = await db.get_queue_depth()

    # Get lists by status
    pending = await db.get_captures_by_status("pending")
    transcribing = await db.get_captures_by_status("transcribing")
    classifying = await db.get_captures_by_status("classifying")
    posting = await db.get_captures_by_status("posting")
    failed = await db.get_captures_by_status("failed")
    complete = await db.get_captures_by_status("complete")

    # Calculate totals
    in_progress_count = len(transcribing) + len(classifying) + len(posting)
    total = sum(queue_depth.values())

    return {
        "counts": {
            "pending": len(pending),
            "transcribing": len(transcribing),
            "classifying": len(classifying),
            "posting": len(posting),
            "failed": len(failed),
            "complete": len(complete),
            "in_progress": in_progress_count,
            "total": total,
        },
        "pending": pending,
        "transcribing": transcribing,
        "classifying": classifying,
        "posting": posting,
        "failed": failed,
        "queue_depth": queue_depth,
    }


def print_summary(status: dict, console: Console) -> None:
    """Print queue summary."""
    counts = status["counts"]

    # Summary table
    table = Table(title="Queue Summary", show_header=True)
    table.add_column("Status", style="cyan")
    table.add_column("Count", justify="right")

    # Pending
    pending_style = "yellow" if counts["pending"] > 0 else "dim"
    table.add_row("Pending", f"[{pending_style}]{counts['pending']}[/{pending_style}]")

    # In Progress (broken down)
    if counts["transcribing"] > 0:
        table.add_row("  Transcribing", f"[blue]{counts['transcribing']}[/blue]")
    if counts["classifying"] > 0:
        table.add_row("  Classifying", f"[blue]{counts['classifying']}[/blue]")
    if counts["posting"] > 0:
        table.add_row("  Posting", f"[blue]{counts['posting']}[/blue]")

    # Failed
    failed_style = "red" if counts["failed"] > 0 else "dim"
    table.add_row("Failed", f"[{failed_style}]{counts['failed']}[/{failed_style}]")

    # Complete
    table.add_row("Complete", f"[green]{counts['complete']}[/green]")

    # Total
    table.add_row("", "")
    table.add_row("[bold]Total[/bold]", f"[bold]{counts['total']}[/bold]")

    console.print(table)


def print_failed_items(failed: list, console: Console, verbose: bool = False) -> None:
    """Print failed items with error details."""
    if not failed:
        console.print("\n[dim]No failed captures.[/dim]")
        return

    console.print()

    table = Table(title="Failed Captures", show_header=True)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Filename")
    table.add_column("Retries", justify="right")
    table.add_column("Last Error")
    if verbose:
        table.add_column("Failed At")
        table.add_column("Captured At")

    for capture in failed:
        # Truncate long error messages
        error = capture.last_error or "Unknown error"
        max_error_len = 60 if not verbose else 80
        if len(error) > max_error_len:
            error = error[: max_error_len - 3] + "..."

        row = [
            str(capture.id),
            capture.filename,
            str(capture.retry_count),
            error,
        ]

        if verbose:
            last_attempt = capture.last_attempt_at
            if last_attempt:
                if isinstance(last_attempt, str):
                    row.append(last_attempt[:19])  # Just date and time
                else:
                    row.append(last_attempt.strftime("%Y-%m-%d %H:%M:%S"))
            else:
                row.append("-")

            captured = capture.captured_at
            if captured:
                if isinstance(captured, str):
                    row.append(captured[:19])
                else:
                    row.append(captured.strftime("%Y-%m-%d %H:%M:%S"))
            else:
                row.append("-")

        table.add_row(*row)

    console.print(table)

    # Hint about retry command
    console.print()
    console.print("[dim]Use 'python -m src.cli.retry --capture-id <ID>' to retry a specific capture[/dim]")
    console.print("[dim]Use 'python -m src.cli.retry --all-failed' to retry all failed captures[/dim]")


def print_pending_items(pending: list, console: Console) -> None:
    """Print pending items."""
    if not pending:
        console.print("\n[dim]No pending captures.[/dim]")
        return

    console.print()

    table = Table(title="Pending Captures", show_header=True)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Filename")
    table.add_column("Device")
    table.add_column("Created At")

    for capture in pending:
        created = capture.created_at
        if created:
            if isinstance(created, str):
                created_str = created[:19]
            else:
                created_str = created.strftime("%Y-%m-%d %H:%M:%S")
        else:
            created_str = "-"

        table.add_row(
            str(capture.id),
            capture.filename,
            capture.device or "unknown",
            created_str,
        )

    console.print(table)


def print_in_progress_items(status: dict, console: Console) -> None:
    """Print in-progress items."""
    in_progress = status["transcribing"] + status["classifying"] + status["posting"]

    if not in_progress:
        console.print("\n[dim]No captures currently processing.[/dim]")
        return

    console.print()

    table = Table(title="In Progress", show_header=True)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Filename")
    table.add_column("Stage", style="blue")
    table.add_column("Started At")

    for capture in status["transcribing"]:
        started = capture.last_attempt_at or capture.updated_at
        if started:
            if isinstance(started, str):
                started_str = started[:19]
            else:
                started_str = started.strftime("%Y-%m-%d %H:%M:%S")
        else:
            started_str = "-"

        table.add_row(str(capture.id), capture.filename, "transcribing", started_str)

    for capture in status["classifying"]:
        started = capture.last_attempt_at or capture.updated_at
        if started:
            if isinstance(started, str):
                started_str = started[:19]
            else:
                started_str = started.strftime("%Y-%m-%d %H:%M:%S")
        else:
            started_str = "-"

        table.add_row(str(capture.id), capture.filename, "classifying", started_str)

    for capture in status["posting"]:
        started = capture.last_attempt_at or capture.updated_at
        if started:
            if isinstance(started, str):
                started_str = started[:19]
            else:
                started_str = started.strftime("%Y-%m-%d %H:%M:%S")
        else:
            started_str = "-"

        table.add_row(str(capture.id), capture.filename, "posting", started_str)

    console.print(table)


def print_http_server_status(settings, console: Console) -> None:
    """Print HTTP server configuration status."""
    console.print()

    http_settings = settings.http

    if http_settings.enabled:
        auth_status = "[green]enabled[/green]" if http_settings.api_key else "[yellow]disabled[/yellow]"
        status_line = f"[green]Enabled[/green] on {http_settings.host}:{http_settings.port} (auth: {auth_status})"
    else:
        status_line = "[dim]Disabled[/dim]"

    console.print(f"[bold]HTTP Server:[/bold] {status_line}")


async def get_http_stats(db: Database) -> dict:
    """Get HTTP upload statistics.

    Args:
        db: Database instance.

    Returns:
        Dict with HTTP stats.
    """
    source_stats = await db.get_source_stats(hours=24)
    recent_http = await db.get_recent_http_uploads(limit=10)

    http_stats = source_stats.get("http", {})
    watcher_stats = source_stats.get("watcher", {})

    http_total = sum(http_stats.values())
    watcher_total = sum(watcher_stats.values())

    return {
        "http_stats": http_stats,
        "watcher_stats": watcher_stats,
        "http_total_24h": http_total,
        "watcher_total_24h": watcher_total,
        "recent_http": recent_http,
    }


def print_http_stats(http_data: dict, console: Console, verbose: bool = False) -> None:
    """Print HTTP upload statistics."""
    console.print()

    # Summary table
    table = Table(title="Upload Sources (Last 24 Hours)", show_header=True)
    table.add_column("Source", style="cyan")
    table.add_column("Total", justify="right")
    table.add_column("Complete", justify="right", style="green")
    table.add_column("Failed", justify="right", style="red")
    table.add_column("Pending", justify="right", style="yellow")

    # HTTP row
    http_stats = http_data["http_stats"]
    http_complete = http_stats.get("complete", 0)
    http_failed = http_stats.get("failed", 0)
    http_pending = http_stats.get("pending", 0) + http_stats.get("transcribing", 0) + \
                   http_stats.get("classifying", 0) + http_stats.get("posting", 0)

    table.add_row(
        "HTTP Upload",
        str(http_data["http_total_24h"]),
        str(http_complete),
        str(http_failed),
        str(http_pending),
    )

    # Watcher row
    watcher_stats = http_data["watcher_stats"]
    watcher_complete = watcher_stats.get("complete", 0)
    watcher_failed = watcher_stats.get("failed", 0)
    watcher_pending = watcher_stats.get("pending", 0) + watcher_stats.get("transcribing", 0) + \
                      watcher_stats.get("classifying", 0) + watcher_stats.get("posting", 0)

    table.add_row(
        "Folder Watcher",
        str(http_data["watcher_total_24h"]),
        str(watcher_complete),
        str(watcher_failed),
        str(watcher_pending),
    )

    console.print(table)

    # Recent HTTP uploads
    recent = http_data["recent_http"]
    if recent:
        console.print()

        recent_table = Table(title="Recent HTTP Uploads", show_header=True)
        recent_table.add_column("ID", style="cyan", justify="right")
        recent_table.add_column("Filename")
        recent_table.add_column("Status")
        recent_table.add_column("Template")
        recent_table.add_column("Created At")

        for capture in recent:
            status_style = {
                "complete": "green",
                "failed": "red",
                "pending": "yellow",
            }.get(capture.status, "dim")

            created = capture.created_at
            if created:
                if isinstance(created, str):
                    created_str = created[:19]
                else:
                    created_str = created.strftime("%Y-%m-%d %H:%M:%S")
            else:
                created_str = "-"

            template = capture.template_name or "-"

            recent_table.add_row(
                str(capture.id),
                capture.filename[:40] + "..." if len(capture.filename) > 40 else capture.filename,
                f"[{status_style}]{capture.status}[/{status_style}]",
                template,
                created_str,
            )

        console.print(recent_table)
    else:
        console.print("\n[dim]No HTTP uploads in the last 24 hours.[/dim]")


@click.command()
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show additional details",
)
@click.option(
    "--failed", "-f",
    is_flag=True,
    help="Show only failed items",
)
@click.option(
    "--pending", "-p",
    is_flag=True,
    help="Show only pending items",
)
@click.option(
    "--in-progress", "-i",
    is_flag=True,
    help="Show only in-progress items",
)
@click.option(
    "--http", "-H",
    is_flag=True,
    help="Show HTTP server status and upload statistics",
)
def queue_status_cli(
    verbose: bool,
    failed: bool,
    pending: bool,
    in_progress: bool,
    http: bool,
) -> None:
    """Show processing queue status.

    Displays counts of captures in each processing state and
    lists failed items with their error messages.

    Examples:
        python -m src.cli.queue_status
        python -m src.cli.queue_status --verbose
        python -m src.cli.queue_status --failed
        python -m src.cli.queue_status --pending
        python -m src.cli.queue_status --http

    Exit codes:
        0 - Status retrieved successfully
        1 - Error retrieving status
    """
    console = Console()
    console.print("\n[bold]Voice Capture Queue Status[/bold]\n")

    try:
        # Initialize
        reload_settings()
        settings = get_settings()

        async def run():
            db = Database(settings.paths.database)
            await db.initialize()

            try:
                # HTTP-only view
                if http:
                    print_http_server_status(settings, console)
                    http_data = await get_http_stats(db)
                    print_http_stats(http_data, console, verbose)

                    # Show timestamp
                    console.print()
                    console.print(f"[dim]As of: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC[/dim]")
                    return 0

                status = await get_queue_status(db)

                # Filter view mode
                show_all = not (failed or pending or in_progress)

                if show_all:
                    print_summary(status, console)
                    # Also show HTTP server status in the default view
                    print_http_server_status(settings, console)

                if show_all or failed:
                    print_failed_items(status["failed"], console, verbose)

                if show_all or pending:
                    print_pending_items(status["pending"], console)

                if show_all or in_progress:
                    print_in_progress_items(status, console)

                # Show timestamp
                console.print()
                console.print(f"[dim]As of: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC[/dim]")

                return 0

            finally:
                await db.close()

        exit_code = asyncio.run(run())
        sys.exit(exit_code)

    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]\n")
        sys.exit(1)


# Entry point for `python -m src.cli.queue_status`
if __name__ == "__main__":
    queue_status_cli()
