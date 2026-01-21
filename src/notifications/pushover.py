"""Pushover notification service for Voice Capture.

Provides integration with Pushover (pushover.net) for system notifications
including processing failures, daily summaries, and health alerts.

Per TDD 4.5:
- send_notification() with title, message, priority (-2 to 2), optional URL
- notify_processing_failure() with priority 0 (Normal)
- send_daily_summary() with priority -1 (Low)
- High failure rate alert (>20%) with priority 1 (High)
- Queue backup alert (>10 items) with priority 0 (Normal)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class NotificationPriority(IntEnum):
    """Pushover notification priority levels.

    Values map directly to Pushover API priority values:
    - LOWEST (-2): No notification, no sound
    - LOW (-1): Quiet notification
    - NORMAL (0): Normal notification
    - HIGH (1): Bypasses quiet hours
    - EMERGENCY (2): Requires acknowledgment (not used in this app)
    """
    LOWEST = -2
    LOW = -1
    NORMAL = 0
    HIGH = 1
    EMERGENCY = 2


@dataclass
class DailyStats:
    """Statistics for daily summary notification.

    Attributes:
        date: The date these stats cover (YYYY-MM-DD).
        completed: Number of successfully processed captures.
        failed: Number of failed captures.
        pending: Number of captures still pending in queue.
        total_audio_seconds: Total audio duration processed.
        failure_rate: Calculated failure rate (0.0-1.0).
    """
    date: str
    completed: int
    failed: int
    pending: int
    total_audio_seconds: float = 0.0

    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as a decimal (0.0-1.0)."""
        total = self.completed + self.failed
        if total == 0:
            return 0.0
        return self.failed / total


class PushoverService:
    """Pushover notification integration.

    Sends notifications via the Pushover API for various system events:
    - Processing failures (after max retries)
    - Daily health summaries
    - High failure rate alerts
    - Queue backup alerts

    All notification methods are async and handle errors gracefully -
    notification failures are logged but do not raise exceptions.
    """

    PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(
        self,
        api_token: str,
        user_key: str,
        device: Optional[str] = None,
        enabled: bool = True,
    ):
        """Initialize Pushover service.

        Args:
            api_token: Pushover application API token.
            user_key: Pushover user key (or group key).
            device: Optional specific device name to send to.
                    If None, sends to all user's devices.
            enabled: Whether notifications are enabled.
                     Allows disabling without removing config.
        """
        self.api_token = api_token
        self.user_key = user_key
        self.device = device
        self.enabled = enabled

        # Rate limiting state
        self._last_notification_time: Optional[datetime] = None
        self._min_interval_seconds = 10  # Minimum seconds between notifications

    async def send_notification(
        self,
        title: str,
        message: str,
        priority: int = NotificationPriority.NORMAL,
        url: Optional[str] = None,
        url_title: Optional[str] = None,
    ) -> bool:
        """Send a Pushover notification.

        Args:
            title: Notification title (max 250 chars).
            message: Notification body (max 1024 chars).
            priority: Notification priority (-2 to 2).
            url: Optional supplementary URL (max 512 chars).
            url_title: Title for the URL (max 100 chars).

        Returns:
            True if notification was sent successfully, False otherwise.
            Returns True if notifications are disabled (no-op success).
        """
        if not self.enabled:
            logger.debug("Notifications disabled, skipping send")
            return True

        if not self.api_token or not self.user_key:
            logger.warning("Pushover credentials not configured, skipping notification")
            return False

        # Rate limiting check
        if not self._check_rate_limit():
            logger.debug("Rate limit active, skipping notification")
            return False

        # Validate and truncate inputs per Pushover API limits
        title = title[:250] if title else ""
        message = message[:1024] if message else ""
        priority = max(-2, min(2, priority))  # Clamp to valid range

        if url:
            url = url[:512]
        if url_title:
            url_title = url_title[:100]

        # Build request payload
        payload = {
            "token": self.api_token,
            "user": self.user_key,
            "title": title,
            "message": message,
            "priority": priority,
        }

        if self.device:
            payload["device"] = self.device
        if url:
            payload["url"] = url
        if url_title:
            payload["url_title"] = url_title

        # Send notification
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.PUSHOVER_API_URL,
                    data=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        self._last_notification_time = datetime.now()
                        logger.info(f"Notification sent: {title}")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Pushover API error: status={response.status}, "
                            f"response={error_text}"
                        )
                        return False

        except aiohttp.ClientError as e:
            logger.error(f"Failed to send notification: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error sending notification: {e}")
            return False

    async def notify_processing_failure(
        self,
        filename: str,
        error_message: str,
        stage: str,
        notion_page_url: Optional[str] = None,
    ) -> bool:
        """Notify about a processing failure.

        Sends a Normal priority (0) notification when a capture fails
        processing after exhausting all retries.

        Args:
            filename: Name of the failed audio file.
            error_message: Error message describing the failure.
            stage: Pipeline stage where failure occurred
                   (transcribing, classifying, posting).
            notion_page_url: Optional URL to Notion page if partially created.

        Returns:
            True if notification sent successfully.
        """
        title = "Voice Capture: Processing Failed"
        message = f"Failed: {filename}\nError: {error_message}\nStage: {stage}"

        url = notion_page_url
        url_title = "View in Notion" if notion_page_url else None

        logger.warning(f"Processing failure notification: {filename} at {stage}")

        return await self.send_notification(
            title=title,
            message=message,
            priority=NotificationPriority.NORMAL,
            url=url,
            url_title=url_title,
        )

    async def send_daily_summary(self, stats: DailyStats) -> bool:
        """Send daily health summary notification.

        Sends a Low priority (-1) notification with daily processing statistics.

        Args:
            stats: DailyStats object with processing statistics.

        Returns:
            True if notification sent successfully.
        """
        title = f"Voice Capture: Daily Summary ({stats.date})"

        # Build summary message
        lines = [
            f"{stats.completed} processed, {stats.failed} failed",
            f"Queue: {stats.pending} pending",
        ]

        if stats.total_audio_seconds > 0:
            minutes = stats.total_audio_seconds / 60
            lines.append(f"Audio: {minutes:.1f} min processed")

        if stats.failed > 0:
            failure_pct = stats.failure_rate * 100
            lines.append(f"Failure rate: {failure_pct:.1f}%")

        message = "\n".join(lines)

        logger.info(f"Sending daily summary: completed={stats.completed}, failed={stats.failed}")

        return await self.send_notification(
            title=title,
            message=message,
            priority=NotificationPriority.LOW,
        )

    async def notify_high_failure_rate(
        self,
        failure_rate: float,
        failed_count: int,
        total_count: int,
    ) -> bool:
        """Alert about high failure rate (>20%).

        Sends a High priority (1) notification when failure rate exceeds
        the configured threshold.

        Args:
            failure_rate: Failure rate as decimal (0.0-1.0).
            failed_count: Number of failed captures.
            total_count: Total number of captures processed.

        Returns:
            True if notification sent successfully.
        """
        title = "Voice Capture: High Failure Rate Alert"
        failure_pct = failure_rate * 100
        message = (
            f"Alert: {failure_pct:.1f}% failure rate today\n"
            f"Failed: {failed_count}/{total_count} captures\n"
            f"Check logs for details"
        )

        logger.error(f"High failure rate alert: {failure_pct:.1f}%")

        return await self.send_notification(
            title=title,
            message=message,
            priority=NotificationPriority.HIGH,
        )

    async def notify_queue_backup(self, pending_count: int) -> bool:
        """Alert about queue backup (>10 items).

        Sends a Normal priority (0) notification when queue depth
        exceeds the configured threshold.

        Args:
            pending_count: Number of items pending in queue.

        Returns:
            True if notification sent successfully.
        """
        title = "Voice Capture: Queue Backed Up"
        message = (
            f"Queue backed up: {pending_count} items pending\n"
            f"Processing may be delayed"
        )

        logger.warning(f"Queue backup alert: {pending_count} items pending")

        return await self.send_notification(
            title=title,
            message=message,
            priority=NotificationPriority.NORMAL,
        )

    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits.

        Prevents notification spam by enforcing a minimum interval
        between notifications.

        Returns:
            True if notification is allowed, False if rate limited.
        """
        if self._last_notification_time is None:
            return True

        elapsed = (datetime.now() - self._last_notification_time).total_seconds()
        return elapsed >= self._min_interval_seconds
