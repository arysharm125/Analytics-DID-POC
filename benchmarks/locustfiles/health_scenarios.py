"""Load testing scenarios for the /health endpoint.

This provides a baseline reference for system responsiveness without
database or authentication overhead.
"""
from common import BaseAPIUser
from locust import between, task


class HealthUser(BaseAPIUser):
    """User that continuously checks the health endpoint.

    This serves as a baseline metric for minimal API latency.
    """
    weight = 1
    wait_time = between(0.1, 0.5)  # Wait 100-500ms between requests

    @task
    def check_health(self):
        """GET /health endpoint."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                # Validate response structure
                data = response.json()
                if "status" in data and "version" in data:
                    response.success()
                else:
                    response.failure("Missing required fields in health response")
            else:
                response.failure(f"Health check returned {response.status_code}")
