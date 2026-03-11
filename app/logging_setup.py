"""Logging configuration for the application.

This module handles logging setup that was previously done at module level in main.py.
Extracting it here makes it easier to test and allows for conditional configuration.
"""

import logging
import logging.config

from app.request_id import RequestIdFilter


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


def apply_request_id_filter() -> None:
    """Apply RequestIdFilter to all handlers programmatically.

    This ensures all loggers (including uvicorn) have the request_id filter.
    """
    request_id_filter = RequestIdFilter()
    for handler in logging.root.handlers:
        handler.addFilter(request_id_filter)
