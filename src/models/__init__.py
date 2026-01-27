"""
Domain models for the Voice Capture pipeline.

This module contains the core data structures used throughout the pipeline:
- ProcessingStatus: State machine states for capture processing
- TranscriptionResult: Output from transcription service
- ClassificationResult: Output from LLM classification
- CaptureRecord: Full capture record with all processing state
"""

from src.models.capture import (
    ProcessingStatus,
    CaptureRecord,
)
from src.models.transcription import TranscriptionResult
from src.models.classification import ClassificationResult

__all__ = [
    "ProcessingStatus",
    "TranscriptionResult",
    "ClassificationResult",
    "CaptureRecord",
]
