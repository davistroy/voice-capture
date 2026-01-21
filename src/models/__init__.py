"""
Domain models for the Voice Capture pipeline.

This module contains the core data structures used throughout the pipeline:
- ProcessingStatus: State machine states for capture processing
- Device: Source device enumeration (Watch, Phone, Unknown)
- TranscriptionResult: Output from transcription service
- ClassificationResult: Output from LLM classification
- CaptureRecord: Full capture record with all processing state
"""

from src.models.capture import (
    ProcessingStatus,
    Device,
    CaptureRecord,
)
from src.models.transcription import TranscriptionResult
from src.models.classification import ClassificationResult

__all__ = [
    "ProcessingStatus",
    "Device",
    "TranscriptionResult",
    "ClassificationResult",
    "CaptureRecord",
]
