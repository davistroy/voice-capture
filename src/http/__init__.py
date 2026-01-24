"""HTTP upload server module for Voice Capture.

This module provides an alternative ingestion path for audio files,
allowing direct uploads via iOS Shortcuts over Tailscale instead of
going through Google Drive/rclone.

Key components:
- HttpUploadServer: Main server class with lifecycle management
- Response helpers: Standardized JSON responses for API endpoints
"""

from src.http.responses import ErrorCode, error_response, health_response, success_response
from src.http.server import HttpUploadServer

__all__ = [
    "HttpUploadServer",
    "ErrorCode",
    "success_response",
    "error_response",
    "health_response",
]
