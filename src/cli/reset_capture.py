"""Reset capture CLI command for Voice Capture.

Moves a failed file back to the inbox directory and clears its failed status
in the database, allowing it to be reprocessed from scratch.

Usage:
    python -m src.cli.reset_capture --filename "2026-01-20T143022_watch.m4a"
    python -m src.cli.reset_capture --capture-id 42

Exit codes:
    0 - Reset completed successfully
    1 - Reset failed or capture not found
"""

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel

from src.config.settings import get_settings, reload_settings
from src.db.database import Database


async def reset_capture_by_id(
    db: Database,
    capture_id: int,
    inbox_path: Path,
) -> dict:
    """Reset a capture by ID.

    Moves the file back to inbox and clears the database status.

    Args:
        db: Database instance.
        capture_id: ID of the capture to reset.
        inbox_path: Path to inbox directory.

    Returns:
        Dict with success status and details.
    """
    capture = await db.get_capture_by_id(capture_id)
    if not capture:
        return {
            "success": False,
            "error": f"Capture with ID {capture_id} not found",
        }

    return await _do_reset(db, capture, inbox_path)


async def reset_capture_by_filename(
    db: Database,
    filename: str,
    inbox_path: Path,
) -> dict:
    """Reset a capture by filename.

    Moves the file back to inbox and clears the database status.

    Args:
        db: Database instance.
        filename: Filename of the capture to reset.
        inbox_path: Path to inbox directory.

    Returns:
        Dict with success status and details.
    """
    capture = await db.get_capture_by_filename(filename)
    if not capture:
        return {
            "success": False,
            "error": f"Capture with filename '{filename}' not found",
        }

    return await _do_reset(db, capture, inbox_path)


async def _do_reset(db: Database, capture, inbox_path: Path) -> dict:
    """Perform the actual reset operation.

    Args:
        db: Database instance.
        capture: CaptureRow to reset.
        inbox_path: Path to inbox directory.

    Returns:
        Dict with success status and details.
    """
    capture_id = capture.id
    filename = capture.filename
    current_path = capture.current_path or capture.original_path

    file_moved = False
    file_found = False

    # Try to find and move the file
    if current_path:
        source_path = Path(current_path)
        if source_path.exists():
            file_found = True
            dest_path = inbox_path / source_path.name

            # Ensure inbox exists
            inbox_path.mkdir(parents=True, exist_ok=True)

            try:
                shutil.move(str(source_path), str(dest_path))
                file_moved = True

                # Update database with new path
                await db.update_current_path(capture_id, str(dest_path))
            except Exception as e:
                return {
                    "success": False,
                    "capture_id": capture_id,
                    "filename": filename,
                    "error": f"Failed to move file: {e}",
                }

    # Reset database status
    reset_success = await db.reset_capture(capture_id)

    if not reset_success:
        return {
            "success": False,
            "capture_id": capture_id,
            "filename": filename,
            "error": "Failed to reset database status",
        }

    return {
        "success": True,
        "capture_id": capture_id,
        "filename": filename,
        "file_found": file_found,
        "file_moved": file_moved,
        "new_path": str(inbox_path / Path(current_path).name) if file_moved else None,
    }


@click.command()
@click.option(
    "--filename", "-f",
    type=str,
    help="Filename of the capture to reset",
)
@click.option(
    "--capture-id", "-c",
    type=int,
    help="ID of the capture to reset",
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
def reset_capture_cli(
    filename: Optional[str],
    capture_id: Optional[int],
    yes: bool,
) -> None:
    """Reset a failed capture for reprocessing.

    Moves the audio file back to the inbox directory and clears the
    failed status in the database. The file will be detected by the
    watcher and reprocessed from the beginning.

    Examples:
        python -m src.cli.reset_capture --filename "2026-01-20T143022_watch.m4a"
        python -m src.cli.reset_capture --capture-id 42
        python -m src.cli.reset_capture -f "recording.m4a" -y

    Exit codes:
        0 - Reset completed successfully
        1 - Reset failed or capture not found
    """
    console = Console()
    console.print("\n[bold]Voice Capture Reset[/bold]\n")

    # Validate arguments
    if not filename and not capture_id:
        console.print("[red]Error: Must specify --filename or --capture-id[/red]")
        sys.exit(1)

    if filename and capture_id:
        console.print("[red]Error: Cannot specify both --filename and --capture-id[/red]")
        sys.exit(1)

    try:
        # Initialize
        reload_settings()
        settings = get_settings()

        async def run():
            db = Database(settings.paths.database)
            await db.initialize()

            try:
                # Get capture info first to show details
                if capture_id:
                    capture = await db.get_capture_by_id(capture_id)
                    if not capture:
                        console.print(f"[red]Capture {capture_id} not found[/red]")
                        return 1
                else:
                    capture = await db.get_capture_by_filename(filename)
                    if not capture:
                        console.print(f"[red]Capture with filename '{filename}' not found[/red]")
                        return 1

                # Show capture details
                console.print(f"Capture: [cyan]{capture.filename}[/cyan]")
                console.print(f"  ID: {capture.id}")
                console.print(f"  Status: {capture.status}")
                console.print(f"  Retries: {capture.retry_count}")
                if capture.last_error:
                    error_display = capture.last_error
                    if len(error_display) > 80:
                        error_display = error_display[:77] + "..."
                    console.print(f"  Last Error: {error_display}")
                console.print()

                # Warn if not in failed state
                if capture.status != "failed":
                    console.print(
                        f"[yellow]Warning: Capture is not in failed state "
                        f"(current: {capture.status})[/yellow]"
                    )

                # Confirm (destructive operation)
                if not yes:
                    console.print(
                        "[yellow]This will reset the capture to pending status and "
                        "move the file back to inbox for reprocessing.[/yellow]"
                    )
                    if not click.confirm("Continue?"):
                        console.print("[dim]Cancelled.[/dim]")
                        return 1

                # Perform reset
                console.print("\nResetting capture...")

                if capture_id:
                    result = await reset_capture_by_id(db, capture_id, settings.paths.inbox)
                else:
                    result = await reset_capture_by_filename(db, filename, settings.paths.inbox)

                if result["success"]:
                    console.print(Panel(
                        f"[green]Reset successful![/green]\n\n"
                        f"Capture ID: {result['capture_id']}\n"
                        f"Filename: {result['filename']}\n"
                        f"File moved: {'Yes' if result.get('file_moved') else 'No'}\n"
                        + (f"New path: {result['new_path']}" if result.get('new_path') else ""),
                        title="Result",
                        border_style="green",
                    ))

                    if not result.get("file_found"):
                        console.print(
                            "[yellow]Note: Audio file was not found. "
                            "You may need to manually place the file in the inbox.[/yellow]"
                        )

                    return 0
                else:
                    console.print(f"[red]Reset failed: {result.get('error')}[/red]")
                    return 1

            finally:
                await db.close()

        exit_code = asyncio.run(run())
        sys.exit(exit_code)

    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]\n")
        sys.exit(1)


# Entry point for `python -m src.cli.reset_capture`
if __name__ == "__main__":
    reset_capture_cli()
