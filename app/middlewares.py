"""Exception handling middleware and handlers for the FastAPI application."""

import logging
import traceback
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_config

logger = logging.getLogger("deployment")


def _build_error_response(request: Request, status_code: int, exc: Exception, detail: str | None = None) -> JSONResponse:
    """Build standardized error response with trace ID.

    Args:
        request: The FastAPI request object
        status_code: HTTP status code for the response
        exc: The exception that was raised
        detail: Optional custom error message

    Returns:
        JSONResponse with standardized error format including trace_id
    """
    trace_id = str(uuid.uuid4())

    # Log the exception with trace ID and request details
    logger.error(
        f"Unhandled exception [trace_id={trace_id}] "
        f"{request.method} {request.url.path}\n"
        f"{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}"
    )

    error_response = {
        "error": "Internal Server Error",
        "trace_id": trace_id,
        "message": detail or "An unexpected error occurred. Please reference the trace_id when reporting this issue."
    }

    # Conditionally include traceback in response for development
    config = get_config()
    if config.expose_error_details:
        error_response["traceback"] = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )

    return JSONResponse(status_code=status_code, content=error_response)


def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTPExceptions - apply trace_id logging for 5xx errors.

    For status codes >= 500, this logs the exception with a trace_id and
    returns a standardized error response. For other status codes (400, 404,
    409, etc.), it returns the default FastAPI response format.

    Args:
        request: The FastAPI request object
        exc: The HTTPException that was raised

    Returns:
        JSONResponse with appropriate format based on status code
    """
    if exc.status_code >= 500:
        return _build_error_response(request, exc.status_code, exc, exc.detail)

    # For non-5xx errors, use default FastAPI behavior
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None)
    )


async def exception_handler_middleware(request: Request, call_next):
    """Middleware to catch unhandled exceptions with trace IDs.

    This middleware catches truly unhandled exceptions (non-HTTPException)
    that would otherwise result in a 500 error without proper logging or
    a standardized response format.

    Args:
        request: The FastAPI request object
        call_next: The next middleware/route handler in the chain

    Returns:
        Response from the next handler, or error response if exception occurs
    """
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        return _build_error_response(request, 500, exc)
