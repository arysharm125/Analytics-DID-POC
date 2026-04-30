"""Request ID middleware and context for correlation tracking.

This module provides middleware to:
1. Extract or generate request IDs from incoming requests
2. Store them in context for the request lifetime
3. Include them in response headers
4. Make them available for logging
5. Log access information with request correlation

The request ID enables distributed tracing and log correlation.
"""

import contextvars
import logging
import secrets
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Context variable to store request ID for the current request
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware to track request IDs for correlation and tracing.

    Extracts X-Request-ID from incoming request header or generates a new UUID.
    Stores the ID in a context variable accessible throughout the request lifecycle.
    Adds the X-Request-ID to the response headers.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request with correlation ID tracking.

        Args:
            request: The incoming FastAPI request
            call_next: The next middleware/handler in the chain

        Returns:
            Response with X-Request-ID header added
        """
        # Get or generate request ID (16 random bytes as 32 hex chars, matching nginx format)
        request_id = request.headers.get("X-Request-ID") or secrets.token_bytes(16).hex()
        request_id_ctx.set(request_id)

        # Process request
        response = await call_next(request)

        # Add to response headers
        response.headers["X-Request-ID"] = request_id
        return response


class RequestIdFilter(logging.Filter):
    """Logging filter to inject request ID into log records.

    Adds a 'request_id' attribute to each log record, which can be
    used in logging format strings.

    Example logging format:
        %(asctime)s [%(request_id)s] %(name)s - %(levelname)s - %(message)s
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add request_id attribute to the log record.

        Args:
            record: The log record to modify

        Returns:
            True to allow the record to be logged
        """
        record.request_id = request_id_ctx.get("-")  # type: ignore
        return True


class AccessLogMiddleware:
    """Pure ASGI middleware for access logging with request correlation.

    This middleware logs HTTP access information within the request context,
    ensuring the request_id is available in logs. Unlike uvicorn's access logger
    which runs after context cleanup, this logs while the context is still active.

    Uses pure ASGI (not BaseHTTPMiddleware) to avoid buffering streaming responses.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application to wrap
        """
        self.app = app
        self.logger = logging.getLogger("app.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process the ASGI request with access logging.

        Args:
            scope: The ASGI connection scope
            receive: The receive callable
            send: The send callable
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract request info
        method = scope["method"]
        path = scope["path"]
        query_string = scope.get("query_string", b"").decode()
        full_path = f"{path}?{query_string}" if query_string else path

        # Extract headers first (needed for request ID and client IP)
        headers_dict = dict(scope.get("headers", []))

        # Get or generate request ID (16 random bytes as 32 hex chars, matching nginx format)
        request_id = headers_dict.get(b"x-request-id", b"").decode() or secrets.token_bytes(16).hex()
        request_id_ctx.set(request_id)

        # Extract real client IP and port
        # Priority: X-Real-Client (IP:port) > fallback to direct connection
        real_client = headers_dict.get(b"x-real-client", b"").decode()

        if real_client:
            # Use IP:port from nginx's X-Real-Client header
            client_addr = real_client
        else:
            # Fallback to direct connection (no proxy)
            client = scope.get("client")
            client_addr = f"{client[0]}:{client[1]}" if client else "-"

        start_time = time.perf_counter()
        status_code = 500  # Default if send never called
        request_size = 0
        response_size = 0

        async def receive_wrapper() -> Message:
            """Wrapper to count request body bytes."""
            nonlocal request_size
            message = await receive()
            if message["type"] == "http.request":
                request_size += len(message.get("body", b""))
            return message

        async def send_wrapper(message: Message) -> None:
            """Wrapper to capture response status code and count response body bytes."""
            nonlocal status_code, response_size
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body":
                response_size += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            # Log access - still within request context so request_id is available
            duration_ms = (time.perf_counter() - start_time) * 1000
            self.logger.info(
                f"{client_addr} - {method} {full_path} {status_code} "
                f"{duration_ms:.2f}ms {request_size}B/{response_size}B"
            )
