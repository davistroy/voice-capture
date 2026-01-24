"""Retry CLI command for Voice Capture.

Allows manual retry of failed captures, either individually or in batch.
Supports restarting from a specific processing stage to preserve work.

Usage:
    python -m src.cli.retry --capture-id 42
    python -m src.cli.retry --all-failed
    python -m src.cli.retry --capture-id 42 --from-stage classifying

Exit codes:
    0 - Retry completed successfully
    1 - Retry failed or no items to retry
"""

import asyncio
import sys
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config.settings import get_settings, reload_settings
from src.db.database import Database


VALID_STAGES = ["pending", "transcribing", "classifying", "posting"]


async def retry_capture(
    db: Database,
    capture_id: int,
    from_stage: Optional[str] = None,
) -> dict:
    """Retry a single failed capture.

    Args:
        db: Database instance.
        capture_id: ID of the capture to retry.
        from_stage: Optional stage to restart from.

    Returns:
        Dict with success, capture_id, and any error message.
    """
    from src.pipeline.orchestrator import PipelineOrchestrator
    from src.transcription.service import TranscriptionService
    from src.transcription.whisper_api import WhisperAPIBackend
    from src.notion.client import NotionService
    from src.classification import ClassificationService, TemplateLoader

    settings = get_settings()

    # Get the capture first to validate it exists
    capture = await db.get_capture_by_id(capture_id)
    if not capture:
        return {
            "success": False,
            "capture_id": capture_id,
            "error": "Capture not found",
        }

    # Initialize services
    whisper_backend = WhisperAPIBackend(
        api_key=settings.openai_api_key,
        model=settings.transcription.model,
        timeout=settings.transcription.timeout_seconds,
    )
    transcription_service = TranscriptionService(backend=whisper_backend)

    notion_service = NotionService(
        api_key=settings.notion_api_key,
        database_id=settings.notion_voice_captures_db_id,
    )

    # Try to load classification service and templates (Phase 2+)
    classification_service = None
    template_loader = None
    try:
        template_loader = TemplateLoader.from_directory(settings.paths.templates)

        classification_service = ClassificationService(
            api_key=settings.anthropic_api_key,
            template_loader=template_loader,
            model=settings.classification.model,
            confidence_threshold=settings.classification.confidence_threshold,
            max_tokens=settings.classification.max_tokens,
        )
    except Exception:
        # Classification not available, will use Phase 1 behavior
        pass

    # Create orchestrator
    orchestrator = PipelineOrchestrator(
        db=db,
        transcription=transcription_service,
        notion=notion_service,
        failed_path=settings.paths.failed,
        classification=classification_service,
        template_loader=template_loader,
    )

    # Perform retry
    result = await orchestrator.retry_failed(capture_id, from_stage=from_stage)

    return {
        "success": result.success,
        "capture_id": capture_id,
        "notion_page_id": result.notion_page_id,
        "notion_page_url": result.notion_page_url,
        "error": result.error,
        "stage": result.stage,
    }


async def retry_all_failed(db: Database, from_stage: Optional[str] = None) -> list[dict]:
    """Retry all failed captures.

    Args:
        db: Database instance.
        from_stage: Optional stage to restart from for all captures.

    Returns:
        List of dicts with results for each capture.
    """
    failed_captures = await db.get_captures_by_status("failed")

    if not failed_captures:
        return []

    results = []
    for capture in failed_captures:
        result = await retry_capture(db, capture.id, from_stage)
        results.append(result)

    return results


async def get_failed_captures(db: Database) -> list:
    """Get list of failed captures with details."""
    return await db.get_captures_by_status("failed")


def print_retry_result(result: dict, console: Console) -> None:
    """Print a single retry result."""
    capture_id = result.get("capture_id")
    success = result.get("success", False)

    if success:
        console.print(f"  [green]Capture {capture_id}: SUCCESS[/green]")
        if result.get("notion_page_url"):
            console.print(f"    Notion URL: {result['notion_page_url']}")
    else:
        error = result.get("error", "Unknown error")
        stage = result.get("stage", "unknown")
        console.print(f"  [red]Capture {capture_id}: FAILED at {stage}[/red]")
        console.print(f"    Error: {error}")


def print_failed_captures_table(captures: list, console: Console) -> None:
    """Print table of failed captures."""
    table = Table(title="Failed Captures", show_header=True)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Filename")
    table.add_column("Retries", justify="right")
    table.add_column("Last Error")

    for capture in captures:
        # Truncate long error messages
        error = capture.last_error or "Unknown"
        if len(error) > 50:
            error = error[:47] + "..."

        table.add_row(
            str(capture.id),
            capture.filename,
            str(capture.retry_count),
            error,
        )

    console.print(table)


@click.command()
@click.option(
    "--capture-id", "-c",
    type=int,
    help="ID of the specific capture to retry",
)
@click.option(
    "--all-failed", "-a",
    is_flag=True,
    help="Retry all failed captures",
)
@click.option(
    "--from-stage", "-s",
    type=click.Choice(VALID_STAGES),
    help="Stage to restart from (preserves prior work)",
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.option(
    "--list", "-l",
    "list_failed",
    is_flag=True,
    help="List failed captures without retrying",
)
def retry_cli(
    capture_id: Optional[int],
    all_failed: bool,
    from_stage: Optional[str],
    yes: bool,
    list_failed: bool,
) -> None:
    """Retry failed voice captures.

    Retry a single capture by ID or all failed captures at once.
    Optionally restart from a specific processing stage to preserve
    already-completed work (e.g., transcription).

    Examples:
        python -m src.cli.retry --capture-id 42
        python -m src.cli.retry --all-failed
        python -m src.cli.retry -c 42 --from-stage classifying
        python -m src.cli.retry --list

    Exit codes:
        0 - Retry completed successfully (at least one success)
        1 - Retry failed or no items to retry
    """
    console = Console()
    console.print("\n[bold]Voice Capture Retry[/bold]\n")

    # Validate arguments
    if not capture_id and not all_failed and not list_failed:
        console.print("[red]Error: Must specify --capture-id, --all-failed, or --list[/red]")
        sys.exit(1)

    if capture_id and all_failed:
        console.print("[red]Error: Cannot specify both --capture-id and --all-failed[/red]")
        sys.exit(1)

    try:
        # Initialize
        reload_settings()
        settings = get_settings()

        async def run():
            db = Database(settings.paths.database)
            await db.initialize()

            try:
                # List mode
                if list_failed:
                    failed = await get_failed_captures(db)
                    if not failed:
                        console.print("[dim]No failed captures found.[/dim]")
                        return 0

                    print_failed_captures_table(failed, console)
                    return 0

                # Retry single capture
                if capture_id:
                    # Verify capture exists and is failed
                    capture = await db.get_capture_by_id(capture_id)
                    if not capture:
                        console.print(f"[red]Capture {capture_id} not found[/red]")
                        return 1

                    if capture.status != "failed" and not yes:
                        console.print(
                            f"[yellow]Warning: Capture {capture_id} is not in failed state "
                            f"(current: {capture.status})[/yellow]"
                        )
                        if not click.confirm("Continue anyway?"):
                            console.print("[dim]Cancelled.[/dim]")
                            return 1

                    stage_info = f" from {from_stage}" if from_stage else ""
                    console.print(f"Retrying capture {capture_id}{stage_info}...")

                    result = await retry_capture(db, capture_id, from_stage)
                    print_retry_result(result, console)

                    return 0 if result["success"] else 1

                # Retry all failed
                if all_failed:
                    failed = await get_failed_captures(db)
                    if not failed:
                        console.print("[dim]No failed captures to retry.[/dim]")
                        return 0

                    # Show what will be retried
                    console.print(f"Found {len(failed)} failed capture(s):\n")
                    print_failed_captures_table(failed, console)
                    console.print()

                    # Confirm
                    if not yes:
                        if not click.confirm(f"Retry all {len(failed)} failed captures?"):
                            console.print("[dim]Cancelled.[/dim]")
                            return 1

                    console.print(f"\nRetrying {len(failed)} captures...\n")

                    results = await retry_all_failed(db, from_stage)

                    # Print results
                    succeeded = sum(1 for r in results if r.get("success"))
                    failed_count = len(results) - succeeded

                    console.print()
                    for result in results:
                        print_retry_result(result, console)

                    console.print()
                    if succeeded > 0:
                        console.print(Panel(
                            f"[green]{succeeded}[/green] succeeded, "
                            f"[red]{failed_count}[/red] failed",
                            title="Results",
                            border_style="green" if failed_count == 0 else "yellow",
                        ))

                    return 0 if succeeded > 0 else 1

            finally:
                await db.close()

        exit_code = asyncio.run(run())
        sys.exit(exit_code)

    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]\n")
        sys.exit(1)


# Entry point for `python -m src.cli.retry`
if __name__ == "__main__":
    retry_cli()
