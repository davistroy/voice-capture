"""Queue status CLI command for Voice Capture.

Shows the current processing queue status including pending, processing,
and failed items with their error messages.

Usage:
    python -m src.cli.queue_status
    python -m src.cli.queue_status --verbose
    python -m src.cli.queue_status --failed

Exit codes:
    0 - Status retrieved successfully
    1 - Error retrieving status
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
def queue_status_cli(
    verbose: bool,
    failed: bool,
    pending: bool,
    in_progress: bool,
) -> None:
    """Show processing queue status.

    Displays counts of captures in each processing state and
    lists failed items with their error messages.

    Examples:
        python -m src.cli.queue_status
        python -m src.cli.queue_status --verbose
        python -m src.cli.queue_status --failed
        python -m src.cli.queue_status --pending

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
                status = await get_queue_status(db)

                # Filter view mode
                show_all = not (failed or pending or in_progress)

                if show_all:
                    print_summary(status, console)

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
