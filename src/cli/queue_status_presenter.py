"""Presentation layer for queue status using Rich.

This module handles all Rich console output formatting,
separated from data fetching concerns.

Classes:
    QueueStatusPresenter: Presenter for queue status display
"""

from datetime import datetime
from typing import Any, Optional

from rich.console import Console
from rich.table import Table

from src.cli.queue_status_query import (
    FailureInfo,
    HttpStats,
    InProgressInfo,
    PendingInfo,
    QueueCounts,
    QueueStatusData,
    RecentUploadInfo,
)


def _format_datetime(dt: Optional[datetime]) -> str:
    """Format a datetime for display.

    Args:
        dt: Datetime to format, or None

    Returns:
        Formatted string or "-" if None
    """
    if dt is None:
        return "-"
    if isinstance(dt, str):
        return dt[:19]  # Just date and time
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class QueueStatusPresenter:
    """Presentation layer for queue status using Rich.

    Handles all Rich console output formatting, including tables
    and styled text. Designed to be testable with a mock Console.

    Usage:
        presenter = QueueStatusPresenter(Console())
        presenter.display(data, verbose=True)
    """

    def __init__(self, console: Console):
        """Initialize the presenter.

        Args:
            console: Rich Console instance for output
        """
        self._console = console

    def display(
        self,
        data: QueueStatusData,
        verbose: bool = False,
        show_http_status: bool = False,
        http_enabled: bool = False,
        http_host: str = "",
        http_port: int = 0,
        http_auth_enabled: bool = False,
    ) -> None:
        """Display complete queue status.

        Args:
            data: Queue status data to display
            verbose: Whether to show additional details
            show_http_status: Whether to show HTTP server status line
            http_enabled: Whether HTTP server is enabled
            http_host: HTTP server host
            http_port: HTTP server port
            http_auth_enabled: Whether HTTP auth is enabled
        """
        self._print_summary(data.counts)

        if show_http_status:
            self._print_http_server_status(
                http_enabled, http_host, http_port, http_auth_enabled
            )

        self._print_failed_items(data.failed_items, verbose)
        self._print_pending_items(data.pending_items)
        self._print_in_progress_items(data.in_progress_items)

        self._print_timestamp()

    def display_failed_only(
        self,
        data: QueueStatusData,
        verbose: bool = False,
    ) -> None:
        """Display only failed items.

        Args:
            data: Queue status data
            verbose: Whether to show additional details
        """
        self._print_failed_items(data.failed_items, verbose)
        self._print_timestamp()

    def display_pending_only(self, data: QueueStatusData) -> None:
        """Display only pending items.

        Args:
            data: Queue status data
        """
        self._print_pending_items(data.pending_items)
        self._print_timestamp()

    def display_in_progress_only(self, data: QueueStatusData) -> None:
        """Display only in-progress items.

        Args:
            data: Queue status data
        """
        self._print_in_progress_items(data.in_progress_items)
        self._print_timestamp()

    def display_http_only(
        self,
        http_stats: HttpStats,
        verbose: bool = False,
        http_enabled: bool = False,
        http_host: str = "",
        http_port: int = 0,
        http_auth_enabled: bool = False,
    ) -> None:
        """Display HTTP server status and statistics.

        Args:
            http_stats: HTTP statistics data
            verbose: Whether to show additional details
            http_enabled: Whether HTTP server is enabled
            http_host: HTTP server host
            http_port: HTTP server port
            http_auth_enabled: Whether HTTP auth is enabled
        """
        self._print_http_server_status(
            http_enabled, http_host, http_port, http_auth_enabled
        )
        self._print_http_stats(http_stats, verbose)
        self._print_timestamp()

    def _print_summary(self, counts: QueueCounts) -> None:
        """Print queue summary table."""
        table = Table(title="Queue Summary", show_header=True)
        table.add_column("Status", style="cyan")
        table.add_column("Count", justify="right")

        # Pending
        pending_style = "yellow" if counts.pending > 0 else "dim"
        table.add_row(
            "Pending", f"[{pending_style}]{counts.pending}[/{pending_style}]"
        )

        # In Progress (broken down)
        if counts.transcribing > 0:
            table.add_row(
                "  Transcribing", f"[blue]{counts.transcribing}[/blue]"
            )
        if counts.classifying > 0:
            table.add_row(
                "  Classifying", f"[blue]{counts.classifying}[/blue]"
            )
        if counts.posting > 0:
            table.add_row("  Posting", f"[blue]{counts.posting}[/blue]")

        # Failed
        failed_style = "red" if counts.failed > 0 else "dim"
        table.add_row("Failed", f"[{failed_style}]{counts.failed}[/{failed_style}]")

        # Complete
        table.add_row("Complete", f"[green]{counts.complete}[/green]")

        # Total
        table.add_row("", "")
        table.add_row("[bold]Total[/bold]", f"[bold]{counts.total}[/bold]")

        self._console.print(table)

    def _print_failed_items(
        self,
        failed_items: list[FailureInfo],
        verbose: bool = False,
    ) -> None:
        """Print failed items with error details."""
        if not failed_items:
            self._console.print("\n[dim]No failed captures.[/dim]")
            return

        self._console.print()

        table = Table(title="Failed Captures", show_header=True)
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Filename")
        table.add_column("Retries", justify="right")
        table.add_column("Last Error")
        if verbose:
            table.add_column("Failed At")
            table.add_column("Captured At")

        for item in failed_items:
            # Truncate long error messages
            error = item.error_message
            max_error_len = 60 if not verbose else 80
            if len(error) > max_error_len:
                error = error[: max_error_len - 3] + "..."

            row = [
                str(item.capture_id),
                item.filename,
                str(item.retry_count),
                error,
            ]

            if verbose:
                row.append(_format_datetime(item.last_attempt_at))
                row.append(_format_datetime(item.captured_at))

            table.add_row(*row)

        self._console.print(table)

        # Hint about retry command
        self._console.print()
        self._console.print(
            "[dim]Use 'python -m src.cli.retry --capture-id <ID>' "
            "to retry a specific capture[/dim]"
        )
        self._console.print(
            "[dim]Use 'python -m src.cli.retry --all-failed' "
            "to retry all failed captures[/dim]"
        )

    def _print_pending_items(self, pending_items: list[PendingInfo]) -> None:
        """Print pending items."""
        if not pending_items:
            self._console.print("\n[dim]No pending captures.[/dim]")
            return

        self._console.print()

        table = Table(title="Pending Captures", show_header=True)
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Filename")
        table.add_column("Device")
        table.add_column("Created At")

        for item in pending_items:
            table.add_row(
                str(item.capture_id),
                item.filename,
                item.device,
                _format_datetime(item.created_at),
            )

        self._console.print(table)

    def _print_in_progress_items(
        self, in_progress_items: list[InProgressInfo]
    ) -> None:
        """Print in-progress items."""
        if not in_progress_items:
            self._console.print("\n[dim]No captures currently processing.[/dim]")
            return

        self._console.print()

        table = Table(title="In Progress", show_header=True)
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Filename")
        table.add_column("Stage", style="blue")
        table.add_column("Started At")

        for item in in_progress_items:
            table.add_row(
                str(item.capture_id),
                item.filename,
                item.stage,
                _format_datetime(item.started_at),
            )

        self._console.print(table)

    def _print_http_server_status(
        self,
        enabled: bool,
        host: str,
        port: int,
        auth_enabled: bool,
    ) -> None:
        """Print HTTP server configuration status."""
        self._console.print()

        if enabled:
            auth_status = "[green]enabled[/green]" if auth_enabled else "[yellow]disabled[/yellow]"
            status_line = (
                f"[green]Enabled[/green] on {host}:{port} "
                f"(auth: {auth_status})"
            )
        else:
            status_line = "[dim]Disabled[/dim]"

        self._console.print(f"[bold]HTTP Server:[/bold] {status_line}")

    def _print_http_stats(self, http_stats: HttpStats, verbose: bool = False) -> None:
        """Print HTTP upload statistics."""
        self._console.print()

        # Summary table
        table = Table(title="Upload Sources (Last 24 Hours)", show_header=True)
        table.add_column("Source", style="cyan")
        table.add_column("Total", justify="right")
        table.add_column("Complete", justify="right", style="green")
        table.add_column("Failed", justify="right", style="red")
        table.add_column("Pending", justify="right", style="yellow")

        # HTTP row
        http = http_stats.http_source
        table.add_row(
            "HTTP Upload",
            str(http.total),
            str(http.complete),
            str(http.failed),
            str(http.pending),
        )

        # Watcher row
        watcher = http_stats.watcher_source
        table.add_row(
            "Folder Watcher",
            str(watcher.total),
            str(watcher.complete),
            str(watcher.failed),
            str(watcher.pending),
        )

        self._console.print(table)

        # Recent HTTP uploads
        if http_stats.recent_uploads:
            self._console.print()
            self._print_recent_uploads(http_stats.recent_uploads)
        else:
            self._console.print("\n[dim]No HTTP uploads in the last 24 hours.[/dim]")

    def _print_recent_uploads(self, uploads: list[RecentUploadInfo]) -> None:
        """Print recent HTTP uploads table."""
        table = Table(title="Recent HTTP Uploads", show_header=True)
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Filename")
        table.add_column("Status")
        table.add_column("Template")
        table.add_column("Created At")

        for upload in uploads:
            status_style = {
                "complete": "green",
                "failed": "red",
                "pending": "yellow",
            }.get(upload.status, "dim")

            filename = upload.filename
            if len(filename) > 40:
                filename = filename[:40] + "..."

            table.add_row(
                str(upload.capture_id),
                filename,
                f"[{status_style}]{upload.status}[/{status_style}]",
                upload.template_name or "-",
                _format_datetime(upload.created_at),
            )

        self._console.print(table)

    def _print_timestamp(self) -> None:
        """Print current timestamp."""
        self._console.print()
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self._console.print(f"[dim]As of: {now} UTC[/dim]")
