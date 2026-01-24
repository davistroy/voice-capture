"""Standardized JSON response helpers for HTTP API endpoints.

Provides consistent response format for success and error cases:

Success response:
{
    "success": true,
    "capture_id": 42,
    "status": "complete",
    "template": "task",
    "notion_url": "https://notion.so/page-id",
    "processing_time_ms": 3450
}

Error response:
{
    "success": false,
    "error": "invalid_audio_format",
    "message": "File must be M4A, MP3, WAV, or WEBM",
    "capture_id": null
}
"""

from enum import Enum
from typing import Any

from aiohttp import web


class ErrorCode(str, Enum):
    """Standard error codes for API responses."""

    INVALID_REQUEST = "invalid_request"
    INVALID_AUDIO_FORMAT = "invalid_audio_format"
    FILE_TOO_LARGE = "file_too_large"
    MISSING_FILE = "missing_file"
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHENTICATION_FAILED = "authentication_failed"
    NOT_FOUND = "not_found"
    PROCESSING_FAILED = "processing_failed"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"


# HTTP status codes for each error code
ERROR_STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.INVALID_AUDIO_FORMAT: 400,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.MISSING_FILE: 400,
    ErrorCode.AUTHENTICATION_REQUIRED: 401,
    ErrorCode.AUTHENTICATION_FAILED: 401,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.PROCESSING_FAILED: 500,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
}


def success_response(
    capture_id: int,
    status: str,
    *,
    template: str | None = None,
    notion_url: str | None = None,
    processing_time_ms: int | None = None,
    extra: dict[str, Any] | None = None,
) -> web.Response:
    """Create a successful JSON response.

    Args:
        capture_id: The ID of the capture record
        status: Current processing status (pending, transcribing, classifying, posting, complete, failed)
        template: Template name if classification is complete
        notion_url: Notion page URL if posting is complete
        processing_time_ms: Total processing time in milliseconds
        extra: Additional fields to include in the response

    Returns:
        aiohttp web.Response with JSON body
    """
    body: dict[str, Any] = {
        "success": True,
        "capture_id": capture_id,
        "status": status,
    }

    if template is not None:
        body["template"] = template

    if notion_url is not None:
        body["notion_url"] = notion_url

    if processing_time_ms is not None:
        body["processing_time_ms"] = processing_time_ms

    if extra:
        body.update(extra)

    return web.json_response(body, status=200)


def error_response(
    error_code: ErrorCode | str,
    message: str,
    *,
    capture_id: int | None = None,
    http_status: int | None = None,
    extra: dict[str, Any] | None = None,
) -> web.Response:
    """Create an error JSON response.

    Args:
        error_code: Error code (from ErrorCode enum or custom string)
        message: Human-readable error message
        capture_id: The capture ID if one was created before the error
        http_status: Override HTTP status code (default based on error_code)
        extra: Additional fields to include in the response

    Returns:
        aiohttp web.Response with JSON body
    """
    # Normalize error code to string
    if isinstance(error_code, ErrorCode):
        code_str = error_code.value
        status = http_status or ERROR_STATUS_CODES.get(error_code, 500)
    else:
        code_str = error_code
        status = http_status or 500

    body: dict[str, Any] = {
        "success": False,
        "error": code_str,
        "message": message,
        "capture_id": capture_id,
    }

    if extra:
        body.update(extra)

    return web.json_response(body, status=status)


def health_response(
    *,
    healthy: bool = True,
    version: str = "1.0.0",
    http_server: str = "running",
    details: dict[str, Any] | None = None,
) -> web.Response:
    """Create a health check response.

    Args:
        healthy: Overall health status
        version: Application version
        http_server: HTTP server status
        details: Additional health check details

    Returns:
        aiohttp web.Response with JSON body
    """
    body: dict[str, Any] = {
        "healthy": healthy,
        "version": version,
        "http_server": http_server,
    }

    if details:
        body["details"] = details

    status = 200 if healthy else 503
    return web.json_response(body, status=status)
