"""Queue status CLI command for Voice Capture.

Shows the current processing queue status including pending, processing,
and failed items with their error messages.

This module provides a thin orchestration layer that coordinates between
the query layer (data fetching) and presenter layer (Rich output).

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

import click
from rich.console import Console

from src.cli.queue_status_presenter import QueueStatusPresenter
from src.cli.queue_status_query import QueueStatusQuery
from src.config.settings import get_settings, reload_settings
from src.db.database import Database


# ===========================================================================
# Backward Compatibility Functions
# ===========================================================================
# These functions are kept for backward compatibility with existing tests.
# New code should use QueueStatusQuery directly.


async def get_queue_status(db: Database) -> dict:
    """Get current queue status (backward compatibility wrapper).

    Args:
        db: Database instance.

    Returns:
        Dict with queue counts and details.

    Note:
        This function is kept for backward compatibility.
        New code should use QueueStatusQuery.get_status() instead.
    """
    query = QueueStatusQuery(db)
    data = await query.get_status()

    # Get raw capture rows for backward compatibility
    pending = await db.get_captures_by_status("pending")
    transcribing = await db.get_captures_by_status("transcribing")
    classifying = await db.get_captures_by_status("classifying")
    posting = await db.get_captures_by_status("posting")
    failed = await db.get_captures_by_status("failed")

    # Return in the old format for backward compatibility
    return {
        "counts": {
            "pending": data.counts.pending,
            "transcribing": data.counts.transcribing,
            "classifying": data.counts.classifying,
            "posting": data.counts.posting,
            "failed": data.counts.failed,
            "complete": data.counts.complete,
            "in_progress": data.counts.in_progress,
            "total": data.counts.total,
        },
        "pending": pending,
        "transcribing": transcribing,
        "classifying": classifying,
        "posting": posting,
        "failed": failed,
        "queue_depth": await db.get_queue_depth(),
    }


async def get_http_stats(db: Database) -> dict:
    """Get HTTP upload statistics (backward compatibility wrapper).

    Args:
        db: Database instance.

    Returns:
        Dict with HTTP stats.

    Note:
        This function is kept for backward compatibility.
        New code should use QueueStatusQuery.get_http_stats_only() instead.
    """
    query = QueueStatusQuery(db)
    http_stats = await query.get_http_stats_only()

    # Get raw rows for backward compatibility
    recent_http = await db.get_recent_http_uploads(limit=10)
    source_stats = await db.get_source_stats(hours=24)

    return {
        "http_stats": source_stats.get("http", {}),
        "watcher_stats": source_stats.get("watcher", {}),
        "http_total_24h": http_stats.http_source.total,
        "watcher_total_24h": http_stats.watcher_source.total,
        "recent_http": recent_http,
    }


# ===========================================================================
# CLI Command
# ===========================================================================


@click.command()
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show additional details",
)
@click.option(
    "--failed",
    "-f",
    is_flag=True,
    help="Show only failed items",
)
@click.option(
    "--pending",
    "-p",
    is_flag=True,
    help="Show only pending items",
)
@click.option(
    "--in-progress",
    "-i",
    is_flag=True,
    help="Show only in-progress items",
)
@click.option(
    "--http",
    "-H",
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
        reload_settings()
        settings = get_settings()

        async def run() -> int:
            db = Database(settings.paths.database)
            await db.initialize()

            try:
                query = QueueStatusQuery(db)
                presenter = QueueStatusPresenter(console)

                # Get HTTP settings for display
                http_settings = settings.http
                http_enabled = http_settings.enabled
                http_host = http_settings.host
                http_port = http_settings.port
                http_auth_enabled = bool(http_settings.api_key)

                # HTTP-only view
                if http:
                    http_stats = await query.get_http_stats_only()
                    presenter.display_http_only(
                        http_stats,
                        verbose=verbose,
                        http_enabled=http_enabled,
                        http_host=http_host,
                        http_port=http_port,
                        http_auth_enabled=http_auth_enabled,
                    )
                    return 0

                # Get full status data
                data = await query.get_status()

                # Determine view mode
                show_all = not (failed or pending or in_progress)

                if show_all:
                    # Show complete status
                    presenter.display(
                        data,
                        verbose=verbose,
                        show_http_status=True,
                        http_enabled=http_enabled,
                        http_host=http_host,
                        http_port=http_port,
                        http_auth_enabled=http_auth_enabled,
                    )
                elif failed:
                    presenter.display_failed_only(data, verbose=verbose)
                elif pending:
                    presenter.display_pending_only(data)
                elif in_progress:
                    presenter.display_in_progress_only(data)

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
