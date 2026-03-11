"""Main FastAPI application entry point.

This module creates and configures the FastAPI application instance.
Most of the application logic has been extracted into separate modules
for improved testability and maintainability.
"""

from app.app_factory import create_app
from app.logging_setup import configure_logging

# Configure logging (file-based configuration with request ID filter)
configure_logging()

# Create the FastAPI application
app = create_app()
