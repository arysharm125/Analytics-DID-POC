"""Common utilities for Locust scenarios.

Provides base user classes, authentication helpers, and shared behaviors.
"""
from locust import HttpUser
from typing import Optional


class BaseAPIUser(HttpUser):
    """Base Locust user with common API configurations.

    Attributes:
        abstract: Set to True to prevent Locust from running this directly
        host: API host URL (set via CLI or environment)
    """
    abstract = True

    def on_start(self) -> None:
        """Called when a simulated user starts."""
        self.client.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })


class AdvisoryAPIUser(BaseAPIUser):
    """User for testing Advisory API endpoints.

    Automatically includes the advisory API token in all requests.
    """
    abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Read from environment variable or use default test token
        import os
        self.advisory_token = os.environ.get("ADVISORY_API_TOKEN", "test-advisory-token")

    def on_start(self) -> None:
        """Set up Advisory-specific headers."""
        super().on_start()
        self.client.headers.update({
            "X-API-Token": self.advisory_token
        })


class EPDWAPIUser(BaseAPIUser):
    """User for testing EPDW API endpoints.

    Automatically includes the EPDW API token in all requests.
    """
    abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Read from environment variable or use default test token
        import os
        self.epdw_token = os.environ.get("EPDW_API_TOKEN", "test-epdw-token")

    def on_start(self) -> None:
        """Set up EPDW-specific headers."""
        super().on_start()
        self.client.headers.update({
            "X-API-Token": self.epdw_token
        })


def generate_uuid() -> str:
    """Generate a random UUID string for testing.

    Returns:
        UUID string in standard format
    """
    import uuid
    return str(uuid.uuid4())


def generate_multihash() -> str:
    """Generate a valid multihash string for testing.

    Returns:
        Base58-encoded multihash string (SHA-256)
    """
    import hashlib
    import base58

    # Generate random data and hash it
    data = generate_uuid().encode()
    sha256_hash = hashlib.sha256(data).digest()

    # Prefix with SHA-256 multihash identifier (0x12) and length (0x20 = 32 bytes)
    multihash_bytes = b'\x12\x20' + sha256_hash

    # Encode with base58
    return base58.b58encode(multihash_bytes).decode()
