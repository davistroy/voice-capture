"""CLI commands for Voice Capture.

Provides command-line tools for configuration verification,
health checks, and manual recovery operations.

Commands:
    verify_config - Verify configuration and test API connectivity
    (Phase 3 will add: retry, reset_capture, queue_status, health_check)
"""

from src.cli.verify_config import verify_config, verify_config_cli

__all__ = [
    "verify_config",
    "verify_config_cli",
]
