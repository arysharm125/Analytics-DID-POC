"""Logging configuration for the application.

This module handles logging setup that was previously done at module level in main.py.
Extracting it here makes it easier to test and allows for conditional configuration.
"""

import logging
import logging.config
import socket
from types import TracebackType
from typing import Union

from app.request_id import RequestIdFilter


class SuppressOnlyPymongoNameResolution(logging.Filter):
    """
    Filter to suppress pymongo client error about DNS failures.

    These errors are (usually) transient and get quickly and automatically
    resolved, so there's no need to record the full stack trace.
    """

    NAME_OR_SERVICE_MSG = "Name or service not known"  # libc message in many locales
    GAI_ERRNO_EAI_NONAME = -2  # common errno for "name or service not known"


    def __init__(self):
        super().__init__()
        self._debug_logger = logging.getLogger("app.dns_suppress")


    def _iter_exc_chain(self, exc: BaseException):
        """Walk __cause__ / __context__ chain to find root causes."""
        seen = set()
        cur = exc
        while cur and cur not in seen:
            yield cur
            seen.add(cur)
            cur = cur.__cause__ or cur.__context__

    def _is_dns_name_or_service_not_known(
        self,
        exc_info: Union[tuple[type[BaseException], BaseException, TracebackType | None], tuple[None, None, None], None]
    ) -> bool:
        if not exc_info or exc_info == (None, None, None):
            return False
        _, exc, _ = exc_info
        if not exc or not isinstance(exc, BaseException):
            return False

        for e in self._iter_exc_chain(exc):
            # Prefer structural detection first
            if isinstance(e, socket.gaierror):
                # socket.gaierror.args is typically (errno, message)
                errnum = None
                msg = ""
                if len(e.args) >= 1 and isinstance(e.args[0], int):
                    errnum = e.args[0]
                if len(e.args) >= 2 and isinstance(e.args[1], str):
                    msg = e.args[1]

                if errnum == self.GAI_ERRNO_EAI_NONAME:
                    return True
                # Fallback on message text (locale-dependent)
                if self.NAME_OR_SERVICE_MSG in msg:
                    return True

            # Some environments wrap gaierror in OSError or generic Exception; match text as fallback
            if self.NAME_OR_SERVICE_MSG in str(e):
                return True

        return False


    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "pymongo.client":
            return True
        if not getattr(record, "exc_info", None):
            return True
        if self._is_dns_name_or_service_not_known(record.exc_info):
            # Emit one-line breadcrumb without stacktrace
            self._debug_logger.warning("Suppressed PyMongo DNS EAI_NONAME error: %s", record.getMessage())
            return False
        return True


def configure_logging(config_path: str = "deployment/logging.ini") -> None:
    """Configure logging from INI file and apply request ID filter.

    Args:
        config_path: Path to the logging configuration INI file
    """
    # Load logging configuration from file
    logging.config.fileConfig(config_path, disable_existing_loggers=False)

    # Apply request ID filter to all handlers
    apply_request_id_filter()

    # Set log levels for noisy third-party libraries
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Shorten DNS errors to warnings without full stack trace.
    dns_filter = SuppressOnlyPymongoNameResolution()
    for handler in logging.root.handlers:
        handler.addFilter(dns_filter)


def apply_request_id_filter() -> None:
    """Apply RequestIdFilter to all handlers programmatically.

    This ensures all loggers (including uvicorn) have the request_id filter.
    """
    request_id_filter = RequestIdFilter()
    for handler in logging.root.handlers:
        handler.addFilter(request_id_filter)
