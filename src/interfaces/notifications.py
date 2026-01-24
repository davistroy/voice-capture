"""Interface for notification services.

Defines the Protocol for notification service implementations,
enabling loose coupling and easier testing per work item 6.8.
"""

from typing import Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from src.notifications.pushover import DailyStats


class INotificationService(Protocol):
    """Interface for notification services.

    Implementations should handle sending notifications for various
    system events including processing failures, daily summaries,
    and alert conditions.

    Example implementations:
        - PushoverService (Pushover API)
        - MockNotificationService (for testing)

    Usage:
        async def notify_failure(
            service: INotificationService,
            filename: str,
            error: str
        ) -> bool:
            return await service.notify_processing_failure(
                filename=filename,
                error_message=error,
                stage="transcribing"
            )
    """

    async def send_notification(
        self,
        title: str,
        message: str,
        priority: int = 0,
        url: Optional[str] = None,
        url_title: Optional[str] = None,
    ) -> bool:
        """Send a notification.

        Args:
            title: Notification title (max 250 chars).
            message: Notification body (max 1024 chars).
            priority: Notification priority (-2 to 2).
                     -2: Lowest (no notification)
                     -1: Low (quiet)
                      0: Normal
                      1: High (bypasses quiet hours)
                      2: Emergency (requires acknowledgment)
            url: Optional supplementary URL (max 512 chars).
            url_title: Title for the URL (max 100 chars).

        Returns:
            True if notification was sent successfully, False otherwise.
            Returns True if notifications are disabled (no-op success).
        """
        ...

    async def notify_processing_failure(
        self,
        filename: str,
        error_message: str,
        stage: str,
        notion_page_url: Optional[str] = None,
    ) -> bool:
        """Send notification about processing failure.

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
        ...

    async def send_daily_summary(self, stats: "DailyStats") -> bool:
        """Send daily health summary notification.

        Sends a Low priority (-1) notification with daily processing
        statistics.

        Args:
            stats: DailyStats object with processing statistics.

        Returns:
            True if notification sent successfully.
        """
        ...

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
        ...

    async def notify_queue_backup(self, pending_count: int) -> bool:
        """Alert about queue backup (>10 items).

        Sends a Normal priority (0) notification when queue depth
        exceeds the configured threshold.

        Args:
            pending_count: Number of items pending in queue.

        Returns:
            True if notification sent successfully.
        """
        ...
