"""Unit tests for app/middlewares.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.config import (
    AppConfig,
    FeatureFlags,
    MongoCollectionConfig,
    MongoPoolConfig,
    TokenConfig,
    VaultConfig,
    override_config,
)
from app.middlewares import (
    _build_error_response,
    exception_handler_middleware,
    http_exception_handler,
)


class TestBuildErrorResponse:
    """Tests for _build_error_response function."""

    def test_returns_json_response_with_required_keys(self):
        """Response should contain error, trace_id, and message keys."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test/path"

        exc = ValueError("Test error")

        response = _build_error_response(mock_request, 500, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 500

        # Parse response body
        import json
        body = json.loads(bytes(response.body).decode("utf-8"))

        assert "error" in body
        assert "trace_id" in body
        assert "message" in body
        assert body["error"] == "Internal Server Error"
        assert isinstance(body["trace_id"], str)
        assert len(body["trace_id"]) == 36  # UUID4 format

    def test_includes_custom_detail_message(self):
        """Should use custom detail message when provided."""
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/test"

        exc = ValueError("Original error")
        custom_detail = "Custom error message"

        response = _build_error_response(mock_request, 500, exc, detail=custom_detail)

        import json
        body = json.loads(bytes(response.body).decode("utf-8"))

        assert body["message"] == custom_detail

    def test_uses_default_message_when_no_detail(self):
        """Should use default message when detail is None."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        exc = ValueError("Test error")

        response = _build_error_response(mock_request, 500, exc)

        import json
        body = json.loads(bytes(response.body).decode("utf-8"))

        assert "unexpected error occurred" in body["message"]
        assert "trace_id" in body["message"]

    def test_includes_traceback_when_expose_error_details_is_true(self):
        """Traceback should be included when config.expose_error_details=True."""
        # Create test config with expose_error_details=True
        test_config = AppConfig(
            vault=VaultConfig(addr="", token="", mount="", local_mock_path=""),
            tokens=TokenConfig(
                epdw_access_token="",
                advisory_access_token="",
                didcheck_access_token="",
            ),
            mongo_pool=MongoPoolConfig(
                max_pool_size=100,
                min_pool_size=5,
                max_idle_time_ms=30000,
                wait_queue_timeout_ms=5000,
                pool_monitor_interval_s=60,
            ),
            features=FeatureFlags(didcheck_router=False, debug_vc_nquads=False),
            expose_error_details=True,
        )

        override_config(test_config)

        try:
            mock_request = MagicMock()
            mock_request.method = "GET"
            mock_request.url.path = "/test"

            exc = ValueError("Test error with traceback")

            response = _build_error_response(mock_request, 500, exc)

            import json
            body = json.loads(bytes(response.body).decode("utf-8"))

            assert "traceback" in body
            assert "ValueError" in body["traceback"]
            assert "Test error with traceback" in body["traceback"]
        finally:
            override_config(None)

    def test_excludes_traceback_when_expose_error_details_is_false(self):
        """Traceback should be excluded when config.expose_error_details=False."""
        # Create test config with expose_error_details=False
        test_config = AppConfig(
            vault=VaultConfig(addr="", token="", mount="", local_mock_path=""),
            tokens=TokenConfig(
                epdw_access_token="",
                advisory_access_token="",
                didcheck_access_token="",
            ),
            mongo_pool=MongoPoolConfig(
                max_pool_size=100,
                min_pool_size=5,
                max_idle_time_ms=30000,
                wait_queue_timeout_ms=5000,
                pool_monitor_interval_s=60,
            ),
            features=FeatureFlags(didcheck_router=False, debug_vc_nquads=False),
            expose_error_details=False,
        )

        override_config(test_config)

        try:
            mock_request = MagicMock()
            mock_request.method = "GET"
            mock_request.url.path = "/test"

            exc = ValueError("Test error")

            response = _build_error_response(mock_request, 500, exc)

            import json
            body = json.loads(bytes(response.body).decode("utf-8"))

            assert "traceback" not in body
        finally:
            override_config(None)

    def test_logs_exception_with_trace_id_and_request_details(self):
        """Exception should be logged with trace_id and request details."""
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/endpoint"

        exc = ValueError("Logged error")

        with patch("app.middlewares.logger") as mock_logger:
            response = _build_error_response(mock_request, 500, exc)

            # Verify logger.error was called
            mock_logger.error.assert_called_once()

            # Extract log message
            log_message = mock_logger.error.call_args[0][0]

            # Parse trace_id from response
            import json
            body = json.loads(bytes(response.body).decode("utf-8"))
            trace_id = body["trace_id"]

            # Verify log contains trace_id, method, and path
            assert f"trace_id={trace_id}" in log_message
            assert "POST" in log_message
            assert "/api/endpoint" in log_message
            assert "ValueError" in log_message

    def test_handles_different_status_codes(self):
        """Should handle different HTTP status codes correctly."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        exc = ValueError("Test error")

        for status_code in [400, 404, 500, 502, 503]:
            response = _build_error_response(mock_request, status_code, exc)
            assert response.status_code == status_code


class TestHttpExceptionHandler:
    """Tests for http_exception_handler function (sync)."""

    def test_5xx_returns_standardized_error_format(self):
        """500+ errors should use trace_id format."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        exc = HTTPException(status_code=500, detail="Internal server error")

        response = http_exception_handler(mock_request, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 500

        import json
        body = json.loads(bytes(response.body).decode("utf-8"))

        # Should have standardized error format
        assert "error" in body
        assert "trace_id" in body
        assert "message" in body

    def test_502_returns_standardized_error_format(self):
        """502 errors should use trace_id format."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        exc = HTTPException(status_code=502, detail="Bad Gateway")

        response = http_exception_handler(mock_request, exc)

        assert response.status_code == 502

        import json
        body = json.loads(bytes(response.body).decode("utf-8"))

        assert "trace_id" in body
        assert body["message"] == "Bad Gateway"

    def test_4xx_returns_default_fastapi_format(self):
        """4xx errors should use standard {"detail": ...} format."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        exc = HTTPException(status_code=404, detail="Not found")

        response = http_exception_handler(mock_request, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 404

        import json
        body = json.loads(bytes(response.body).decode("utf-8"))

        # Should have default FastAPI format
        assert "detail" in body
        assert body["detail"] == "Not found"

        # Should NOT have trace_id for 4xx errors
        assert "trace_id" not in body
        assert "error" not in body

    def test_400_returns_default_format(self):
        """400 Bad Request should use default format."""
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/test"

        exc = HTTPException(status_code=400, detail="Invalid input")

        response = http_exception_handler(mock_request, exc)

        assert response.status_code == 400

        import json
        body = json.loads(bytes(response.body).decode("utf-8"))

        assert body == {"detail": "Invalid input"}

    def test_409_returns_default_format(self):
        """409 Conflict should use default format."""
        mock_request = MagicMock()
        mock_request.method = "PUT"
        mock_request.url.path = "/api/resource"

        exc = HTTPException(status_code=409, detail="Resource conflict")

        response = http_exception_handler(mock_request, exc)

        assert response.status_code == 409

        import json
        body = json.loads(bytes(response.body).decode("utf-8"))

        assert body == {"detail": "Resource conflict"}

    def test_preserves_exception_headers(self):
        """Headers from HTTPException should be preserved in response."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        custom_headers = {"X-Custom-Header": "custom-value"}
        exc = HTTPException(status_code=404, detail="Not found", headers=custom_headers)

        response = http_exception_handler(mock_request, exc)

        assert response.headers["X-Custom-Header"] == "custom-value"

    def test_handles_exception_without_headers(self):
        """Should handle exceptions without headers attribute gracefully."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        exc = HTTPException(status_code=400, detail="Bad request")
        # Ensure no headers attribute
        if hasattr(exc, "headers"):
            delattr(exc, "headers")

        response = http_exception_handler(mock_request, exc)

        assert response.status_code == 400
        # Should not raise an error


class TestExceptionHandlerMiddleware:
    """Tests for exception_handler_middleware function (async)."""

    @pytest.mark.asyncio
    async def test_passes_through_successful_response(self):
        """Normal responses should pass through unchanged."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def mock_call_next(request):
            return mock_response

        result = await exception_handler_middleware(mock_request, mock_call_next)

        assert result == mock_response

    @pytest.mark.asyncio
    async def test_catches_unhandled_exception_returns_500(self):
        """Unhandled exceptions should return 500 with trace_id."""
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/api/endpoint"

        # Mock call_next that raises an exception
        async def mock_call_next(request):
            raise ValueError("Unhandled error")

        result = await exception_handler_middleware(mock_request, mock_call_next)

        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

        import json
        body = json.loads(bytes(result.body).decode("utf-8"))

        assert "error" in body
        assert "trace_id" in body
        assert "message" in body

    @pytest.mark.asyncio
    async def test_catches_runtime_error(self):
        """Should catch RuntimeError exceptions."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        async def mock_call_next(request):
            raise RuntimeError("Runtime error occurred")

        result = await exception_handler_middleware(mock_request, mock_call_next)

        assert result.status_code == 500

        import json
        body = json.loads(bytes(result.body).decode("utf-8"))

        assert "trace_id" in body

    @pytest.mark.asyncio
    async def test_catches_attribute_error(self):
        """Should catch AttributeError exceptions."""
        mock_request = MagicMock()
        mock_request.method = "DELETE"
        mock_request.url.path = "/api/resource"

        async def mock_call_next(request):
            raise AttributeError("Attribute not found")

        result = await exception_handler_middleware(mock_request, mock_call_next)

        assert result.status_code == 500

        import json
        body = json.loads(bytes(result.body).decode("utf-8"))

        assert "trace_id" in body

    @pytest.mark.asyncio
    async def test_logs_unhandled_exception(self):
        """Unhandled exceptions should be logged with trace_id."""
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        async def mock_call_next(request):
            raise ValueError("Logged exception")

        with patch("app.middlewares.logger") as mock_logger:
            result = await exception_handler_middleware(mock_request, mock_call_next)

            # Verify logger.error was called
            mock_logger.error.assert_called_once()

            # Extract trace_id from response
            import json
            body = json.loads(bytes(result.body).decode("utf-8"))
            trace_id = body["trace_id"]

            # Verify log contains trace_id
            log_message = mock_logger.error.call_args[0][0]
            assert f"trace_id={trace_id}" in log_message
