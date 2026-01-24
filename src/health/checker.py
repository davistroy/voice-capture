"""Health check implementation for Voice Capture.

Provides comprehensive system health monitoring including:
- Database connectivity
- API reachability (OpenAI, Claude, Notion, Pushover)
- Directory permissions
- Processing statistics and alerting rules

Per TDD 10.3 and PRD 9.3:
- Daily health check at 9 PM (configurable)
- Failure rate > 20% triggers high priority alert
- Queue backup > 10 items triggers normal alert
- API unreachable triggers high priority alert
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

from src.config.settings import Settings
from src.db.database import Database
from src.notifications.pushover import DailyStats, NotificationPriority, PushoverService

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """Status of a health check."""
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass
class HealthCheck:
    """Result of a single health check.

    Attributes:
        name: Name of the check.
        status: Pass, fail, warn, or skip.
        message: Description of result.
        details: Optional additional details.
        duration_ms: Time taken to run check in milliseconds.
    """
    name: str
    status: CheckStatus
    message: str
    details: Optional[str] = None
    duration_ms: Optional[float] = None


@dataclass
class ProcessingStats:
    """Processing statistics for health reporting.

    Attributes:
        captures_received_24h: Captures received in last 24 hours.
        captures_completed_24h: Captures completed successfully in last 24 hours.
        captures_failed_24h: Captures failed in last 24 hours.
        current_queue_depth: Current number of pending/processing items.
        failure_rate: Calculated failure rate (0.0-1.0).
        queue_by_status: Breakdown of queue by status.
    """
    captures_received_24h: int = 0
    captures_completed_24h: int = 0
    captures_failed_24h: int = 0
    current_queue_depth: int = 0
    queue_by_status: dict[str, int] = field(default_factory=dict)

    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as a decimal (0.0-1.0)."""
        total = self.captures_completed_24h + self.captures_failed_24h
        if total == 0:
            return 0.0
        return self.captures_failed_24h / total


@dataclass
class HealthCheckResult:
    """Complete health check report.

    Attributes:
        checks: List of individual check results.
        stats: Processing statistics.
        timestamp: When the health check was run.
        passed: Number of passed checks.
        failed: Number of failed checks.
        warnings: Number of warning checks.
        skipped: Number of skipped checks.
        alerts: List of triggered alerts.
    """
    checks: list[HealthCheck] = field(default_factory=list)
    stats: Optional[ProcessingStats] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    skipped: int = 0
    alerts: list[str] = field(default_factory=list)

    def add_check(self, check: HealthCheck) -> None:
        """Add a check result to the report."""
        self.checks.append(check)
        if check.status == CheckStatus.PASS:
            self.passed += 1
        elif check.status == CheckStatus.FAIL:
            self.failed += 1
        elif check.status == CheckStatus.WARN:
            self.warnings += 1
        elif check.status == CheckStatus.SKIP:
            self.skipped += 1

    @property
    def all_passed(self) -> bool:
        """True if no checks failed."""
        return self.failed == 0

    @property
    def is_healthy(self) -> bool:
        """True if system is considered healthy (no failures)."""
        return self.failed == 0


class HealthChecker:
    """Comprehensive health checker for Voice Capture system.

    Runs all health checks and collects processing statistics.
    Can send notifications via Pushover based on alerting rules.

    Usage:
        checker = HealthChecker(settings, db, pushover)
        result = await checker.run_all_checks()
        await checker.send_health_notification(result)
    """

    def __init__(
        self,
        settings: Settings,
        db: Database,
        pushover: Optional[PushoverService] = None,
    ):
        """Initialize health checker.

        Args:
            settings: Application settings.
            db: Database connection.
            pushover: Optional Pushover service for notifications.
        """
        self.settings = settings
        self.db = db
        self.pushover = pushover

    async def run_all_checks(self) -> HealthCheckResult:
        """Run all health checks and collect statistics.

        Returns:
            HealthCheckResult with all check results and stats.
        """
        result = HealthCheckResult()

        # Database connectivity
        result.add_check(await self._check_database())

        # API reachability
        result.add_check(await self._check_openai_api())
        result.add_check(await self._check_claude_api())
        result.add_check(await self._check_notion_api())
        result.add_check(await self._check_pushover_api())

        # Directory permissions
        for check in await self._check_directories():
            result.add_check(check)

        # Collect processing statistics
        result.stats = await self._collect_stats()

        # Evaluate alerting rules
        result.alerts = self._evaluate_alerts(result)

        return result

    async def _check_database(self) -> HealthCheck:
        """Check database connectivity."""
        import time
        start = time.perf_counter()

        try:
            # Simple query to verify connectivity
            queue_depth = await self.db.get_queue_depth()
            duration_ms = (time.perf_counter() - start) * 1000

            return HealthCheck(
                name="Database",
                status=CheckStatus.PASS,
                message=f"Connected - {sum(queue_depth.values())} total records",
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"Database health check failed: {e}")
            return HealthCheck(
                name="Database",
                status=CheckStatus.FAIL,
                message="Connection failed",
                details=str(e)[:200],
                duration_ms=duration_ms,
            )

    async def _check_openai_api(self) -> HealthCheck:
        """Check OpenAI API reachability."""
        import time
        start = time.perf_counter()

        if not self.settings.openai_api_key:
            return HealthCheck(
                name="OpenAI API",
                status=CheckStatus.SKIP,
                message="API key not configured",
            )

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.settings.openai_api_key)

            # Lightweight API call to verify connectivity
            models = await client.models.list()
            duration_ms = (time.perf_counter() - start) * 1000

            # Check if whisper model is available
            model_ids = [m.id for m in models.data]
            has_whisper = any("whisper" in m.lower() for m in model_ids)

            if has_whisper:
                return HealthCheck(
                    name="OpenAI API",
                    status=CheckStatus.PASS,
                    message="Connected - Whisper available",
                    duration_ms=duration_ms,
                )
            else:
                return HealthCheck(
                    name="OpenAI API",
                    status=CheckStatus.WARN,
                    message="Connected but Whisper model not found",
                    duration_ms=duration_ms,
                )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"OpenAI API health check failed: {e}")
            return HealthCheck(
                name="OpenAI API",
                status=CheckStatus.FAIL,
                message="Connection failed",
                details=str(e)[:200],
                duration_ms=duration_ms,
            )

    async def _check_claude_api(self) -> HealthCheck:
        """Check Claude API reachability."""
        import time
        start = time.perf_counter()

        if not self.settings.anthropic_api_key:
            return HealthCheck(
                name="Claude API",
                status=CheckStatus.SKIP,
                message="API key not configured",
            )

        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)

            # Simple API call to verify connectivity
            # Use a minimal prompt to minimize token usage
            message = await client.messages.create(
                model=self.settings.classification.model,
                max_tokens=10,
                messages=[
                    {"role": "user", "content": "Say OK"}
                ],
            )
            duration_ms = (time.perf_counter() - start) * 1000

            return HealthCheck(
                name="Claude API",
                status=CheckStatus.PASS,
                message="Connected",
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"Claude API health check failed: {e}")
            return HealthCheck(
                name="Claude API",
                status=CheckStatus.FAIL,
                message="Connection failed",
                details=str(e)[:200],
                duration_ms=duration_ms,
            )

    async def _check_notion_api(self) -> HealthCheck:
        """Check Notion API reachability."""
        import time
        start = time.perf_counter()

        if not self.settings.notion_api_key:
            return HealthCheck(
                name="Notion API",
                status=CheckStatus.SKIP,
                message="API key not configured",
            )

        if not self.settings.notion_voice_captures_db_id:
            return HealthCheck(
                name="Notion API",
                status=CheckStatus.SKIP,
                message="Database ID not configured",
            )

        try:
            from notion_client import AsyncClient

            client = AsyncClient(auth=self.settings.notion_api_key)

            # Retrieve database metadata to verify access
            # Using databases.retrieve() instead of query() for compatibility
            # with notion-client 2.7.0+ where query() moved to data_sources
            response = await client.databases.retrieve(
                database_id=self.settings.notion_voice_captures_db_id,
            )
            duration_ms = (time.perf_counter() - start) * 1000

            if "id" in response:
                return HealthCheck(
                    name="Notion API",
                    status=CheckStatus.PASS,
                    message="Connected - Database accessible",
                    duration_ms=duration_ms,
                )
            else:
                return HealthCheck(
                    name="Notion API",
                    status=CheckStatus.WARN,
                    message="Connected but unexpected response",
                    duration_ms=duration_ms,
                )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"Notion API health check failed: {e}")
            return HealthCheck(
                name="Notion API",
                status=CheckStatus.FAIL,
                message="Connection failed",
                details=str(e)[:200],
                duration_ms=duration_ms,
            )

    async def _check_pushover_api(self) -> HealthCheck:
        """Check Pushover API reachability."""
        import time
        import aiohttp
        start = time.perf_counter()

        if not self.settings.pushover_api_token or not self.settings.pushover_user_key:
            return HealthCheck(
                name="Pushover API",
                status=CheckStatus.SKIP,
                message="API credentials not configured",
            )

        try:
            # Use the validate endpoint to verify credentials without sending a notification
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.pushover.net/1/users/validate.json",
                    data={
                        "token": self.settings.pushover_api_token,
                        "user": self.settings.pushover_user_key,
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    duration_ms = (time.perf_counter() - start) * 1000
                    result = await response.json()

                    if response.status == 200 and result.get("status") == 1:
                        return HealthCheck(
                            name="Pushover API",
                            status=CheckStatus.PASS,
                            message="Connected - Credentials valid",
                            duration_ms=duration_ms,
                        )
                    else:
                        return HealthCheck(
                            name="Pushover API",
                            status=CheckStatus.FAIL,
                            message="Invalid credentials",
                            details=result.get("errors", ["Unknown error"])[0] if result.get("errors") else None,
                            duration_ms=duration_ms,
                        )

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"Pushover API health check failed: {e}")
            return HealthCheck(
                name="Pushover API",
                status=CheckStatus.FAIL,
                message="Connection failed",
                details=str(e)[:200],
                duration_ms=duration_ms,
            )

    async def _check_directories(self) -> list[HealthCheck]:
        """Check directory permissions."""
        checks = []

        directories = [
            ("Inbox", self.settings.paths.inbox, True, True),
            ("Processing", self.settings.paths.processing, True, True),
            ("Failed", self.settings.paths.failed, True, True),
        ]

        for name, path, need_read, need_write in directories:
            checks.append(self._check_directory(name, path, need_read, need_write))

        return checks

    def _check_directory(
        self,
        name: str,
        path: Path,
        need_read: bool,
        need_write: bool,
    ) -> HealthCheck:
        """Check a single directory for required permissions."""
        try:
            if not path.exists():
                return HealthCheck(
                    name=f"Directory: {name}",
                    status=CheckStatus.FAIL,
                    message=f"Does not exist: {path}",
                )

            can_read = os.access(path, os.R_OK)
            can_write = os.access(path, os.W_OK)

            if need_read and not can_read:
                return HealthCheck(
                    name=f"Directory: {name}",
                    status=CheckStatus.FAIL,
                    message=f"No read permission: {path}",
                )

            if need_write and not can_write:
                return HealthCheck(
                    name=f"Directory: {name}",
                    status=CheckStatus.FAIL,
                    message=f"No write permission: {path}",
                )

            permissions = []
            if can_read:
                permissions.append("read")
            if can_write:
                permissions.append("write")

            return HealthCheck(
                name=f"Directory: {name}",
                status=CheckStatus.PASS,
                message=f"OK ({', '.join(permissions)})",
            )

        except Exception as e:
            return HealthCheck(
                name=f"Directory: {name}",
                status=CheckStatus.FAIL,
                message=f"Error checking: {path}",
                details=str(e)[:200],
            )

    async def _collect_stats(self) -> ProcessingStats:
        """Collect processing statistics from database."""
        try:
            # Get queue depth by status
            queue_depth = await self.db.get_queue_depth()

            # Calculate current queue (pending + in-progress states)
            in_progress_states = {"pending", "transcribing", "classifying", "posting"}
            current_queue = sum(
                count for status, count in queue_depth.items()
                if status in in_progress_states
            )

            # Get stats for last 24 hours
            today = datetime.utcnow().strftime("%Y-%m-%d")
            yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

            # Get daily stats for today and yesterday to cover 24h window
            today_stats = await self.db.get_daily_stats(today)
            yesterday_stats = await self.db.get_daily_stats(yesterday)

            # Combine stats (simplified - just use today's stats for now)
            received = today_stats.captures_received if today_stats else 0
            completed = today_stats.captures_completed if today_stats else 0
            failed = today_stats.captures_failed if today_stats else 0

            return ProcessingStats(
                captures_received_24h=received,
                captures_completed_24h=completed,
                captures_failed_24h=failed,
                current_queue_depth=current_queue,
                queue_by_status=queue_depth,
            )

        except Exception as e:
            logger.error(f"Failed to collect stats: {e}")
            return ProcessingStats()

    def _evaluate_alerts(self, result: HealthCheckResult) -> list[str]:
        """Evaluate alerting rules and return triggered alerts."""
        alerts = []

        # Check for failed API checks
        for check in result.checks:
            if check.status == CheckStatus.FAIL and "API" in check.name:
                alerts.append(f"HIGH: {check.name} unreachable")

        # Check failure rate threshold
        if result.stats:
            if result.stats.failure_rate > self.settings.health_check.failure_rate_threshold:
                failure_pct = result.stats.failure_rate * 100
                alerts.append(f"HIGH: Failure rate {failure_pct:.1f}% exceeds threshold")

            # Check queue backup threshold
            if result.stats.current_queue_depth > self.settings.health_check.queue_backup_threshold:
                alerts.append(
                    f"NORMAL: Queue backup ({result.stats.current_queue_depth} items)"
                )

        return alerts

    async def send_health_notification(self, result: HealthCheckResult) -> bool:
        """Send health check notification via Pushover.

        Sends daily summary and any triggered alerts.

        Args:
            result: Health check result to report.

        Returns:
            True if notification sent successfully.
        """
        if not self.pushover:
            logger.debug("Pushover not configured, skipping notification")
            return False

        # Determine notification priority based on alerts
        has_high_alert = any(alert.startswith("HIGH:") for alert in result.alerts)
        has_api_failure = any(
            check.status == CheckStatus.FAIL and "API" in check.name
            for check in result.checks
        )

        # Send high priority alerts first
        if has_high_alert or has_api_failure:
            await self._send_alert_notification(result)

        # Send daily summary (lower priority)
        return await self._send_summary_notification(result)

    async def _send_alert_notification(self, result: HealthCheckResult) -> bool:
        """Send high priority alert notification."""
        if not self.pushover:
            return False

        # Build alert message
        alert_messages = []

        # API failures
        for check in result.checks:
            if check.status == CheckStatus.FAIL and "API" in check.name:
                alert_messages.append(f"{check.name}: {check.message}")

        # High priority alerts from alerting rules
        for alert in result.alerts:
            if alert.startswith("HIGH:"):
                alert_messages.append(alert.replace("HIGH: ", ""))

        if not alert_messages:
            return True

        title = "Voice Capture: Health Alert"
        message = "\n".join(alert_messages)

        return await self.pushover.send_notification(
            title=title,
            message=message,
            priority=NotificationPriority.HIGH,
        )

    async def _send_summary_notification(self, result: HealthCheckResult) -> bool:
        """Send daily summary notification."""
        if not self.pushover or not result.stats:
            return False

        # Create DailyStats for the notification
        stats = DailyStats(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            completed=result.stats.captures_completed_24h,
            failed=result.stats.captures_failed_24h,
            pending=result.stats.current_queue_depth,
        )

        # Build summary lines
        lines = [
            f"Checks: {result.passed} passed, {result.failed} failed, {result.warnings} warnings",
        ]

        if result.stats.captures_completed_24h > 0 or result.stats.captures_failed_24h > 0:
            lines.append(
                f"24h: {result.stats.captures_completed_24h} completed, "
                f"{result.stats.captures_failed_24h} failed"
            )

        if result.stats.current_queue_depth > 0:
            lines.append(f"Queue: {result.stats.current_queue_depth} pending")

        # Add any normal priority alerts
        for alert in result.alerts:
            if alert.startswith("NORMAL:"):
                lines.append(alert.replace("NORMAL: ", ""))

        title = "Voice Capture: Daily Health Check"
        message = "\n".join(lines)

        # Use low priority for normal daily summary, normal if there are alerts
        priority = NotificationPriority.NORMAL if result.alerts else NotificationPriority.LOW

        return await self.pushover.send_notification(
            title=title,
            message=message,
            priority=priority,
        )
