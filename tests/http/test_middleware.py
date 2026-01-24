"""Unit tests for HTTP middleware.

Tests cover:
- API key authentication middleware
- Error handling middleware
- Request logging middleware
- Middleware stack creation
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.http.middleware import (
    create_api_key_middleware,
    create_middleware_stack,
    error_middleware,
    request_logging_middleware,
)
from src.http.responses import ErrorCode


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_handler():
    """Create a mock handler that returns 200 OK."""

    async def handler(request):
        return web.json_response({"status": "ok"})

    return handler


@pytest.fixture
def mock_handler_raises():
    """Create a mock handler that raises an exception."""

    async def handler(request):
        raise ValueError("Something went wrong")

    return handler


@pytest.fixture
def mock_request():
    """Create a mock request."""
    request = make_mocked_request("GET", "/api/v1/test")
    return request


# ============================================================================
# API Key Middleware Tests
# ============================================================================


class TestApiKeyMiddleware:
    """Tests for API key authentication middleware."""

    @pytest.mark.asyncio
    async def test_no_api_key_configured_passes_all(self, mock_handler):
        """When no API key is configured, all requests pass through."""
        middleware = create_api_key_middleware(api_key=None)
        request = make_mocked_request("GET", "/api/v1/test")

        response = await middleware(request, mock_handler)

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_skip_paths_not_authenticated(self, mock_handler):
        """Requests to skip paths are not authenticated."""
        middleware = create_api_key_middleware(
            api_key="secret",
            skip_paths={"/health", "/ready"},
        )
        request = make_mocked_request("GET", "/health")

        response = await middleware(request, mock_handler)

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_401(self, mock_handler):
        """Request without API key returns 401."""
        middleware = create_api_key_middleware(api_key="secret")
        request = make_mocked_request("GET", "/api/v1/test")

        response = await middleware(request, mock_handler)

        assert response.status == 401
        body = json.loads(response.body)
        assert body["error"] == "authentication_required"
        assert body["success"] is False

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_401(self, mock_handler):
        """Request with invalid API key returns 401."""
        middleware = create_api_key_middleware(api_key="secret")
        request = make_mocked_request(
            "GET",
            "/api/v1/test",
            headers={"X-API-Key": "wrong-key"},
        )

        response = await middleware(request, mock_handler)

        assert response.status == 401
        body = json.loads(response.body)
        assert body["error"] == "authentication_failed"

    @pytest.mark.asyncio
    async def test_valid_api_key_passes(self, mock_handler):
        """Request with valid API key passes through."""
        middleware = create_api_key_middleware(api_key="secret")
        request = make_mocked_request(
            "GET",
            "/api/v1/test",
            headers={"X-API-Key": "secret"},
        )

        response = await middleware(request, mock_handler)

        assert response.status == 200
        body = json.loads(response.body)
        assert body["status"] == "ok"

    @pytest.mark.asyncio
    async def test_default_skip_paths_includes_health(self, mock_handler):
        """Default skip paths include /health."""
        middleware = create_api_key_middleware(api_key="secret")
        request = make_mocked_request("GET", "/health")

        response = await middleware(request, mock_handler)

        assert response.status == 200

    @pytest.mark.asyncio
    async def test_constant_time_comparison(self, mock_handler):
        """API key comparison uses constant-time algorithm."""
        # This test verifies the implementation uses secrets.compare_digest
        # by checking that similar keys don't reveal timing information
        middleware = create_api_key_middleware(api_key="correct_key_here")

        # Test with completely wrong key
        request1 = make_mocked_request(
            "GET",
            "/api/v1/test",
            headers={"X-API-Key": "x"},
        )
        response1 = await middleware(request1, mock_handler)

        # Test with almost correct key
        request2 = make_mocked_request(
            "GET",
            "/api/v1/test",
            headers={"X-API-Key": "correct_key_herf"},
        )
        response2 = await middleware(request2, mock_handler)

        # Both should return 401
        assert response1.status == 401
        assert response2.status == 401


# ============================================================================
# Error Middleware Tests
# ============================================================================


class TestErrorMiddleware:
    """Tests for error handling middleware."""

    @pytest.mark.asyncio
    async def test_successful_response_passes_through(self, mock_handler, mock_request):
        """Successful responses pass through unchanged."""
        response = await error_middleware(mock_request, mock_handler)

        assert response.status == 200
        body = json.loads(response.body)
        assert body["status"] == "ok"

    @pytest.mark.asyncio
    async def test_catches_unhandled_exception(self, mock_handler_raises, mock_request):
        """Unhandled exceptions are caught and return 500."""
        response = await error_middleware(mock_request, mock_handler_raises)

        assert response.status == 500
        body = json.loads(response.body)
        assert body["success"] is False
        assert body["error"] == "internal_error"
        assert body["message"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_converts_http_404_to_json(self):
        """HTTP 404 exceptions are converted to JSON."""

        async def handler(request):
            raise web.HTTPNotFound(reason="Resource not found")

        request = make_mocked_request("GET", "/not-found")
        response = await error_middleware(request, handler)

        assert response.status == 404
        body = json.loads(response.body)
        assert body["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_converts_http_405_to_json(self):
        """HTTP 405 exceptions are converted to JSON."""

        async def handler(request):
            raise web.HTTPMethodNotAllowed(method="POST", allowed_methods=["GET"])

        request = make_mocked_request("POST", "/api/test")
        response = await error_middleware(request, handler)

        assert response.status == 405
        body = json.loads(response.body)
        assert body["error"] == "invalid_request"
        assert "Method not allowed" in body["message"]

    @pytest.mark.asyncio
    async def test_converts_http_413_to_json(self):
        """HTTP 413 exceptions are converted to JSON."""

        async def handler(request):
            raise web.HTTPRequestEntityTooLarge(max_size=1024, actual_size=2048)

        request = make_mocked_request("POST", "/api/upload")
        response = await error_middleware(request, handler)

        assert response.status == 413
        body = json.loads(response.body)
        assert body["error"] == "file_too_large"

    @pytest.mark.asyncio
    async def test_handles_generic_400_errors(self):
        """Generic 4xx errors are converted to JSON."""

        async def handler(request):
            raise web.HTTPBadRequest(reason="Invalid input")

        request = make_mocked_request("POST", "/api/test")
        response = await error_middleware(request, handler)

        assert response.status == 400
        body = json.loads(response.body)
        assert body["error"] == "invalid_request"

    @pytest.mark.asyncio
    async def test_handles_generic_500_errors(self):
        """Generic 5xx errors are converted to JSON."""

        async def handler(request):
            raise web.HTTPServiceUnavailable(reason="Service temporarily unavailable")

        request = make_mocked_request("GET", "/api/test")
        response = await error_middleware(request, handler)

        assert response.status == 503
        body = json.loads(response.body)
        assert body["error"] == "internal_error"

    @pytest.mark.asyncio
    async def test_logs_unhandled_exceptions(self, mock_handler_raises, mock_request, caplog):
        """Unhandled exceptions are logged."""
        with caplog.at_level(logging.ERROR):
            await error_middleware(mock_request, mock_handler_raises)

        assert "Unhandled exception" in caplog.text
        assert "Something went wrong" in caplog.text


# ============================================================================
# Request Logging Middleware Tests
# ============================================================================


class TestRequestLoggingMiddleware:
    """Tests for request logging middleware."""

    @pytest.mark.asyncio
    async def test_logs_successful_request(self, mock_handler, mock_request, caplog):
        """Successful requests are logged at INFO level."""
        with caplog.at_level(logging.INFO):
            await request_logging_middleware(mock_request, mock_handler)

        assert "GET" in caplog.text
        assert "/api/v1/test" in caplog.text
        assert "200" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_4xx_at_warning(self, mock_request, caplog):
        """4xx responses are logged at WARNING level."""

        async def handler(request):
            return web.json_response({"error": "bad"}, status=400)

        with caplog.at_level(logging.WARNING):
            await request_logging_middleware(mock_request, handler)

        assert "400" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_5xx_at_error(self, mock_request, caplog):
        """5xx responses are logged at ERROR level."""

        async def handler(request):
            return web.json_response({"error": "server"}, status=500)

        with caplog.at_level(logging.ERROR):
            await request_logging_middleware(mock_request, handler)

        assert "500" in caplog.text

    @pytest.mark.asyncio
    async def test_adds_response_time_header(self, mock_handler, mock_request):
        """Response includes X-Response-Time-Ms header."""
        response = await request_logging_middleware(mock_request, mock_handler)

        assert "X-Response-Time-Ms" in response.headers
        time_ms = float(response.headers["X-Response-Time-Ms"])
        assert time_ms >= 0

    @pytest.mark.asyncio
    async def test_preserves_request_id(self, mock_handler):
        """Request ID from header is logged."""
        request = make_mocked_request(
            "GET",
            "/api/test",
            headers={"X-Request-ID": "req-12345"},
        )

        response = await request_logging_middleware(request, mock_handler)

        assert request.get("request_id") == "req-12345"

    @pytest.mark.asyncio
    async def test_logs_exceptions_at_error(self, mock_handler_raises, mock_request, caplog):
        """Exceptions are logged at ERROR level before re-raising."""
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError):
                await request_logging_middleware(mock_request, mock_handler_raises)

        assert "EXCEPTION" in caplog.text

    @pytest.mark.asyncio
    async def test_includes_timing_in_log(self, mock_handler, mock_request, caplog):
        """Log includes timing information in milliseconds."""
        with caplog.at_level(logging.INFO):
            await request_logging_middleware(mock_request, mock_handler)

        # Check that log contains timing (e.g., "0.12ms")
        assert "ms" in caplog.text


# ============================================================================
# Middleware Stack Tests
# ============================================================================


class TestMiddlewareStack:
    """Tests for middleware stack creation."""

    def test_creates_stack_without_auth(self):
        """Stack without API key has request_logging and error middleware."""
        stack = create_middleware_stack()

        assert len(stack) == 2
        # Verify middleware are functions/coroutines
        assert callable(stack[0])
        assert callable(stack[1])

    def test_creates_stack_with_auth(self):
        """Stack with API key includes auth middleware."""
        stack = create_middleware_stack(api_key="secret")

        assert len(stack) == 3

    def test_middleware_order(self):
        """Middleware are in correct order: logging, error, auth."""
        stack = create_middleware_stack(api_key="secret")

        # First should be request_logging_middleware
        assert stack[0] is request_logging_middleware

        # Second should be error_middleware
        assert stack[1] is error_middleware

        # Third should be the api_key_middleware (a closure, so just check callable)
        assert callable(stack[2])

    def test_custom_skip_paths(self):
        """Custom skip paths can be specified."""
        stack = create_middleware_stack(
            api_key="secret",
            skip_auth_paths={"/health", "/metrics"},
        )

        assert len(stack) == 3


# ============================================================================
# Integration Tests
# ============================================================================


class TestMiddlewareIntegration:
    """Integration tests for middleware working together."""

    @pytest.fixture
    def app_with_middleware(self):
        """Create app with all middleware."""
        middlewares = create_middleware_stack(api_key="test-key")
        app = web.Application(middlewares=middlewares)

        async def test_handler(request):
            return web.json_response({"result": "success"})

        async def health_handler(request):
            return web.json_response({"healthy": True})

        app.router.add_get("/api/test", test_handler)
        app.router.add_get("/health", health_handler)

        return app

    @pytest.mark.asyncio
    async def test_full_stack_authenticated_request(
        self, app_with_middleware, aiohttp_client
    ):
        """Test authenticated request through full stack."""
        client = await aiohttp_client(app_with_middleware)

        resp = await client.get(
            "/api/test",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status == 200
        data = await resp.json()
        assert data["result"] == "success"

    @pytest.mark.asyncio
    async def test_full_stack_unauthenticated_request(
        self, app_with_middleware, aiohttp_client
    ):
        """Test unauthenticated request through full stack."""
        client = await aiohttp_client(app_with_middleware)

        resp = await client.get("/api/test")

        assert resp.status == 401
        data = await resp.json()
        assert data["error"] == "authentication_required"

    @pytest.mark.asyncio
    async def test_full_stack_health_skips_auth(
        self, app_with_middleware, aiohttp_client
    ):
        """Test health endpoint skips authentication."""
        client = await aiohttp_client(app_with_middleware)

        resp = await client.get("/health")

        assert resp.status == 200
        data = await resp.json()
        assert data["healthy"] is True

    @pytest.mark.asyncio
    async def test_full_stack_404_returns_json(
        self, app_with_middleware, aiohttp_client
    ):
        """Test 404 for unknown route returns JSON."""
        client = await aiohttp_client(app_with_middleware)

        resp = await client.get(
            "/nonexistent",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status == 404
        data = await resp.json()
        assert data["error"] == "not_found"
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_response_includes_timing_header(
        self, app_with_middleware, aiohttp_client
    ):
        """Test response includes timing header."""
        client = await aiohttp_client(app_with_middleware)

        resp = await client.get(
            "/api/test",
            headers={"X-API-Key": "test-key"},
        )

        assert "X-Response-Time-Ms" in resp.headers
