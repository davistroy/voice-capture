"""Interface definitions for voice capture services.

This module provides Protocol-based interfaces for the core services
in the voice capture pipeline. Using Protocols enables:

- Structural subtyping (duck typing with type checking)
- Loose coupling between components
- Easier testing with mock implementations
- Clear API contracts for each service

Interfaces:
    ITranscriptionService: Audio transcription to text
    IClassificationService: Transcript classification into templates
    INotionService: Notion page creation and management
    INotificationService: System notifications and alerts

Usage:
    from src.interfaces import (
        ITranscriptionService,
        IClassificationService,
        INotionService,
        INotificationService,
    )

    # Type hint with protocol for loose coupling
    def process_audio(service: ITranscriptionService) -> TranscriptionResult:
        return await service.transcribe(audio_path)

    # Any class implementing the protocol methods works
    # No explicit inheritance required
"""

from src.interfaces.transcription import ITranscriptionService
from src.interfaces.classification import IClassificationService
from src.interfaces.notion import INotionService
from src.interfaces.notifications import INotificationService

__all__ = [
    "ITranscriptionService",
    "IClassificationService",
    "INotionService",
    "INotificationService",
]
