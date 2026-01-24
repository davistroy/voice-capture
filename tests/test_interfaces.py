"""Tests for interface protocol compliance.

Verifies that the actual service implementations properly satisfy
the Protocol interfaces defined in src/interfaces/.

Work item 6.8: Interface abstractions for services.
"""

import pytest
from pathlib import Path
from typing import Optional, runtime_checkable, Protocol
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.interfaces import (
    ITranscriptionService,
    IClassificationService,
    INotionService,
    INotificationService,
)
from src.models.transcription import TranscriptionResult
from src.models.classification import ClassificationResult


class TestTranscriptionServiceProtocol:
    """Tests for ITranscriptionService protocol compliance."""

    def test_transcription_service_satisfies_protocol(self):
        """TranscriptionService should satisfy ITranscriptionService protocol."""
        from src.transcription.service import TranscriptionService
        from src.transcription.base import TranscriptionBackend

        # Create a mock backend
        mock_backend = MagicMock(spec=TranscriptionBackend)
        mock_backend.name = "mock"
        mock_backend.get_supported_formats.return_value = ["m4a", "mp3"]

        # Create service instance
        service = TranscriptionService(backend=mock_backend)

        # Verify the service has the required method
        assert hasattr(service, "transcribe")
        assert callable(service.transcribe)

    @pytest.mark.asyncio
    async def test_transcription_service_method_signature(self):
        """TranscriptionService.transcribe should match protocol signature."""
        import tempfile
        import os
        from src.transcription.service import TranscriptionService
        from src.transcription.base import TranscriptionBackend

        # Create a mock backend that returns a valid result
        mock_backend = MagicMock(spec=TranscriptionBackend)
        mock_backend.name = "mock"
        mock_backend.transcribe = AsyncMock(
            return_value=TranscriptionResult(
                text="Test transcript",
                duration_seconds=10.0,
                language="en",
            )
        )

        service = TranscriptionService(backend=mock_backend)

        # Create a temporary file to satisfy file existence check
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as f:
            temp_path = Path(f.name)

        try:
            # Call with protocol-defined signature
            result = await service.transcribe(temp_path, language="en")

            # Verify result type
            assert isinstance(result, TranscriptionResult)
            assert result.text == "Test transcript"
        finally:
            # Clean up
            os.unlink(temp_path)


class TestClassificationServiceProtocol:
    """Tests for IClassificationService protocol compliance."""

    def test_classification_service_satisfies_protocol(self):
        """ClassificationService should satisfy IClassificationService protocol."""
        from src.classification.classification import ClassificationService
        from src.classification.template_loader import TemplateLoader

        # Create mock dependencies
        mock_client = MagicMock()
        mock_loader = MagicMock()
        # Mock methods used by prompt builder
        mock_loader.get_enabled_templates.return_value = []
        mock_loader.build_classification_prompt_context.return_value = ""

        # Create service instance
        service = ClassificationService(
            anthropic_client=mock_client,
            template_loader=mock_loader,
        )

        # Verify the service has the required method
        assert hasattr(service, "classify")
        assert callable(service.classify)

    @pytest.mark.asyncio
    async def test_classification_service_method_signature(self):
        """ClassificationService.classify should match protocol signature."""
        from src.classification.classification import ClassificationService
        from src.classification.template_loader import TemplateLoader
        from src.classification.prompt_builder import TranscriptMetadata

        # Create mock dependencies
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"template": "general", "confidence": 0.8, "title": "Test", "tags": [], "fields": {}}')]
        mock_client.messages.create.return_value = mock_response

        mock_loader = MagicMock()
        # Mock methods used by prompt builder
        mock_loader.get_enabled_templates.return_value = []
        mock_loader.build_classification_prompt_context.return_value = ""

        service = ClassificationService(
            anthropic_client=mock_client,
            template_loader=mock_loader,
        )

        # Call with protocol-defined signature
        metadata = TranscriptMetadata(
            captured_at=datetime.now(),
            duration_seconds=10.0,
            device="phone",
        )
        result = await service.classify("Test transcript", metadata=metadata)

        # Verify result type
        assert isinstance(result, ClassificationResult)


class TestNotionServiceProtocol:
    """Tests for INotionService protocol compliance."""

    def test_notion_service_satisfies_protocol(self):
        """NotionService should satisfy INotionService protocol."""
        from src.notion.client import NotionService

        # Create service instance with mock credentials
        service = NotionService(
            api_key="test-api-key",
            database_id="test-db-id",
        )

        # Verify the service has the required methods
        assert hasattr(service, "create_capture_page")
        assert callable(service.create_capture_page)
        assert hasattr(service, "close")
        assert callable(service.close)

    @pytest.mark.asyncio
    async def test_notion_service_method_signature(self):
        """NotionService.create_capture_page should match protocol signature."""
        from src.notion.client import NotionService, CaptureMetadata

        # Create service instance
        service = NotionService(
            api_key="test-api-key",
            database_id="test-db-id",
        )

        # Create test data
        transcription = TranscriptionResult(
            text="Test transcript",
            duration_seconds=10.0,
            language="en",
        )
        metadata = CaptureMetadata(
            captured_at=datetime.now(),
            device="Phone",
            duration_seconds=10.0,
        )

        # Mock the internal client
        with patch.object(service, "_client") as mock_client:
            mock_client.pages.create = AsyncMock(
                return_value={
                    "id": "test-page-id",
                    "url": "https://notion.so/test-page-id",
                }
            )

            # Call with protocol-defined signature
            result = await service.create_capture_page(
                transcription=transcription,
                metadata=metadata,
                title="Test Title",
            )

            # Verify result has expected attributes
            assert hasattr(result, "id")
            assert hasattr(result, "url")


class TestNotificationServiceProtocol:
    """Tests for INotificationService protocol compliance."""

    def test_pushover_service_satisfies_protocol(self):
        """PushoverService should satisfy INotificationService protocol."""
        from src.notifications.pushover import PushoverService

        # Create service instance with mock credentials
        service = PushoverService(
            api_token="test-token",
            user_key="test-user",
        )

        # Verify the service has all required methods
        assert hasattr(service, "send_notification")
        assert callable(service.send_notification)
        assert hasattr(service, "notify_processing_failure")
        assert callable(service.notify_processing_failure)
        assert hasattr(service, "send_daily_summary")
        assert callable(service.send_daily_summary)
        assert hasattr(service, "notify_high_failure_rate")
        assert callable(service.notify_high_failure_rate)
        assert hasattr(service, "notify_queue_backup")
        assert callable(service.notify_queue_backup)

    @pytest.mark.asyncio
    async def test_pushover_service_notify_failure_signature(self):
        """PushoverService.notify_processing_failure should match protocol."""
        from src.notifications.pushover import PushoverService

        # Create service with notifications disabled to avoid actual API calls
        service = PushoverService(
            api_token="test-token",
            user_key="test-user",
            enabled=False,  # Disable to avoid actual API calls
        )

        # Call with protocol-defined signature
        result = await service.notify_processing_failure(
            filename="test.m4a",
            error_message="Test error",
            stage="transcribing",
            notion_page_url=None,
        )

        # When disabled, should return True (no-op success)
        assert result is True

    @pytest.mark.asyncio
    async def test_pushover_service_daily_summary_signature(self):
        """PushoverService.send_daily_summary should match protocol."""
        from src.notifications.pushover import PushoverService, DailyStats

        # Create service with notifications disabled
        service = PushoverService(
            api_token="test-token",
            user_key="test-user",
            enabled=False,
        )

        # Create test stats
        stats = DailyStats(
            date="2024-01-15",
            completed=10,
            failed=2,
            pending=3,
            total_audio_seconds=300.0,
        )

        # Call with protocol-defined signature
        result = await service.send_daily_summary(stats)

        assert result is True


class TestProtocolUsageInOrchestrator:
    """Tests that the orchestrator works with protocol-typed services."""

    def test_orchestrator_accepts_protocol_implementations(self):
        """PipelineOrchestrator should accept protocol-satisfying services."""
        from src.pipeline.orchestrator import PipelineOrchestrator
        from src.transcription.service import TranscriptionService
        from src.transcription.base import TranscriptionBackend
        from src.notion.client import NotionService
        from src.db.database import Database

        # Create mock database
        mock_db = MagicMock(spec=Database)

        # Create mock transcription service
        mock_backend = MagicMock(spec=TranscriptionBackend)
        mock_backend.name = "mock"
        transcription = TranscriptionService(backend=mock_backend)

        # Create mock Notion service
        notion = NotionService(
            api_key="test-key",
            database_id="test-db",
        )

        # Should be able to create orchestrator with these services
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            transcription=transcription,
            notion=notion,
        )

        assert orchestrator is not None
        assert orchestrator._transcription is transcription
        assert orchestrator._notion is notion


class TestMockImplementations:
    """Tests demonstrating mock implementations of protocols."""

    @pytest.mark.asyncio
    async def test_mock_transcription_service(self):
        """A mock class satisfying ITranscriptionService should work."""

        class MockTranscriptionService:
            """Mock transcription service for testing."""

            async def transcribe(
                self,
                audio_path: Path,
                language: Optional[str] = None,
            ) -> TranscriptionResult:
                return TranscriptionResult(
                    text="Mocked transcript",
                    duration_seconds=5.0,
                    language=language or "en",
                )

        mock_service = MockTranscriptionService()
        result = await mock_service.transcribe(Path("/test.m4a"))

        assert result.text == "Mocked transcript"
        assert result.duration_seconds == 5.0

    @pytest.mark.asyncio
    async def test_mock_notification_service(self):
        """A mock class satisfying INotificationService should work."""

        class MockNotificationService:
            """Mock notification service for testing."""

            def __init__(self):
                self.notifications = []

            async def send_notification(
                self,
                title: str,
                message: str,
                priority: int = 0,
                url: Optional[str] = None,
                url_title: Optional[str] = None,
            ) -> bool:
                self.notifications.append({
                    "title": title,
                    "message": message,
                    "priority": priority,
                })
                return True

            async def notify_processing_failure(
                self,
                filename: str,
                error_message: str,
                stage: str,
                notion_page_url: Optional[str] = None,
            ) -> bool:
                return await self.send_notification(
                    title=f"Failed: {filename}",
                    message=error_message,
                )

            async def send_daily_summary(self, stats) -> bool:
                return True

            async def notify_high_failure_rate(
                self,
                failure_rate: float,
                failed_count: int,
                total_count: int,
            ) -> bool:
                return True

            async def notify_queue_backup(self, pending_count: int) -> bool:
                return True

        mock_service = MockNotificationService()
        result = await mock_service.notify_processing_failure(
            filename="test.m4a",
            error_message="Test error",
            stage="transcribing",
        )

        assert result is True
        assert len(mock_service.notifications) == 1
        assert mock_service.notifications[0]["title"] == "Failed: test.m4a"
