"""HTTP middleware for Voice Capture API.

Provides middleware components for:
- API key authentication
- Error handling with consistent JSON responses
- Request logging with timing information

Example usage:
    app = web.Application(
        middlewares=[
            error_middleware,
            request_logging_middleware,
            create_api_key_middleware(api_key="secret"),
        ]
    )
"""

import logging
import secrets
import time
from typing import Awaitable, Callable, Optional

from aiohttp import web

from src.http.responses import ErrorCode, error_response

logger = logging.getLogger(__name__)


# Type alias for aiohttp middleware handler
Handler = Callable[[web.Request], Awaitable[web.Response]]


def create_api_key_middleware(
    api_key: Optional[str] = None,
    skip_paths: Optional[set[str]] = None,
) -> web.middleware:
    """Create an API key authentication middleware.

    When an API key is configured, all requests (except those to skip_paths)
    must include a valid X-API-Key header. If no API key is configured,
    the middleware passes all requests through.

    Args:
        api_key: The API key to validate against. If None, authentication is disabled.
        skip_paths: Set of paths to skip authentication for (e.g., {"/health"}).
            Defaults to {"/health"} if not specified.

    Returns:
        An aiohttp middleware function.

    Example:
        middleware = create_api_key_middleware(api_key="secret")
        app = web.Application(middlewares=[middleware])
    """
    if skip_paths is None:
        skip_paths = {"/health"}

    @web.middleware
    async def api_key_middleware(
        request: web.Request,
        handler: Handler,
    ) -> web.Response:
        """Validate API key header for protected endpoints.

        Args:
            request: The incoming HTTP request.
            handler: The next handler in the chain.

        Returns:
            Response from the next handler or 401 error response.
        """
        # If no API key configured, skip authentication
        if api_key is None:
            return await handler(request)

        # Skip authentication for allowed paths
        if request.path in skip_paths:
            return await handler(request)

        # Check for X-API-Key header
        provided_key = request.headers.get("X-API-Key")

        if not provided_key:
            logger.warning(
                "Authentication required but no API key provided: %s %s",
                request.method,
                request.path,
            )
            return error_response(
                ErrorCode.AUTHENTICATION_REQUIRED,
                "X-API-Key header is required",
            )

        # Use constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(provided_key, api_key):
            logger.warning(
                "Invalid API key provided: %s %s",
                request.method,
                request.path,
            )
            return error_response(
                ErrorCode.AUTHENTICATION_FAILED,
                "Invalid API key",
            )

        return await handler(request)

    return api_key_middleware


@web.middleware
async def error_middleware(
    request: web.Request,
    handler: Handler,
) -> web.Response:
    """Catch unhandled exceptions and return consistent JSON error responses.

    This middleware wraps all handlers to ensure that any unhandled exceptions
    are converted to proper JSON error responses with appropriate status codes.

    Args:
        request: The incoming HTTP request.
        handler: The next handler in the chain.

    Returns:
        Response from the next handler or a JSON error response.
    """
    try:
        return await handler(request)
    except web.HTTPException as e:
        # aiohttp HTTP exceptions (404, 405, etc.) - convert to JSON
        logger.debug(
            "HTTP exception: %s %s -> %d",
            request.method,
            request.path,
            e.status,
        )

        # Map HTTP status codes to error codes
        if e.status == 404:
            return error_response(
                ErrorCode.NOT_FOUND,
                str(e.reason) or "Not found",
                http_status=404,
            )
        elif e.status == 405:
            return error_response(
                ErrorCode.INVALID_REQUEST,
                "Method not allowed",
                http_status=405,
            )
        elif e.status == 413:
            return error_response(
                ErrorCode.FILE_TOO_LARGE,
                str(e.reason) or "Request entity too large",
                http_status=413,
            )
        elif e.status >= 400 and e.status < 500:
            return error_response(
                ErrorCode.INVALID_REQUEST,
                str(e.reason) or "Bad request",
                http_status=e.status,
            )
        else:
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                str(e.reason) or "Server error",
                http_status=e.status,
            )
    except Exception as e:
        # Unexpected exceptions - log and return 500
        logger.exception(
            "Unhandled exception in %s %s: %s",
            request.method,
            request.path,
            e,
        )
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            "Internal server error",
        )


@web.middleware
async def request_logging_middleware(
    request: web.Request,
    handler: Handler,
) -> web.Response:
    """Log all incoming requests with timing information.

    Logs request method, path, and response status with processing time.
    Uses INFO level for successful requests and WARNING for errors.

    Args:
        request: The incoming HTTP request.
        handler: The next handler in the chain.

    Returns:
        Response from the next handler.
    """
    start_time = time.time()
    request_id = request.headers.get("X-Request-ID", "-")

    # Store request_id on request for downstream use
    request["request_id"] = request_id

    try:
        response = await handler(request)
        elapsed_ms = (time.time() - start_time) * 1000

        # Determine log level based on status code
        if response.status >= 500:
            log_func = logger.error
        elif response.status >= 400:
            log_func = logger.warning
        else:
            log_func = logger.info

        log_func(
            "%s %s %d %.2fms [%s]",
            request.method,
            request.path,
            response.status,
            elapsed_ms,
            request_id,
        )

        # Add timing header to response
        response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"

        return response

    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error(
            "%s %s EXCEPTION %.2fms [%s]: %s",
            request.method,
            request.path,
            elapsed_ms,
            request_id,
            e,
        )
        raise


# Convenience function to create all middleware in the correct order
def create_middleware_stack(
    api_key: Optional[str] = None,
    skip_auth_paths: Optional[set[str]] = None,
) -> list[web.middleware]:
    """Create a complete middleware stack with proper ordering.

    The middleware is ordered so that:
    1. request_logging_middleware runs first (logs all requests)
    2. error_middleware catches any errors and converts to JSON
    3. api_key_middleware validates authentication

    Args:
        api_key: Optional API key for authentication. If None, auth is disabled.
        skip_auth_paths: Paths to skip authentication for.

    Returns:
        List of middleware functions in the correct order.
    """
    middlewares: list[web.middleware] = [
        request_logging_middleware,
        error_middleware,
    ]

    if api_key:
        middlewares.append(
            create_api_key_middleware(
                api_key=api_key,
                skip_paths=skip_auth_paths,
            )
        )

    return middlewares
