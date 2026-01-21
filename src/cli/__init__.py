"""CLI commands for Voice Capture.

Provides command-line tools for configuration verification,
health checks, and manual recovery operations.

Commands:
    verify_config - Verify configuration and test API connectivity
    health_check - Run health checks and send notifications
    retry - Retry failed captures
    reset_capture - Reset a capture for reprocessing
    queue_status - Show processing queue status
"""

from src.cli.verify_config import verify_config, verify_config_cli
from src.cli.health_check import run_health_check, health_check_cli
from src.cli.retry import retry_capture, retry_all_failed, retry_cli
from src.cli.reset_capture import reset_capture_by_id, reset_capture_by_filename, reset_capture_cli
from src.cli.queue_status import get_queue_status, queue_status_cli

__all__ = [
    # verify_config
    "verify_config",
    "verify_config_cli",
    # health_check
    "run_health_check",
    "health_check_cli",
    # retry
    "retry_capture",
    "retry_all_failed",
    "retry_cli",
    # reset_capture
    "reset_capture_by_id",
    "reset_capture_by_filename",
    "reset_capture_cli",
    # queue_status
    "get_queue_status",
    "queue_status_cli",
]
