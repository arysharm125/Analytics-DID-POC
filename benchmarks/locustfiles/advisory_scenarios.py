"""Load testing scenarios for Advisory API endpoints.

Tests the following endpoints:
- GET /advisory/did.json (no auth)
- POST /advisory/record_report (requires token)
- GET /advisory/{uid}/vc.json (requires token)
"""
from locust import task, between
from common import AdvisoryAPIUser, BaseAPIUser, generate_uuid, generate_multihash


class AdvisoryDIDDocumentUser(BaseAPIUser):
    """User that fetches the Advisory division DID document.

    This is a public endpoint (no auth required).
    """
    weight = 2
    wait_time = between(0.5, 2.0)

    @task
    def get_did_document(self):
        """GET /advisory/did.json"""
        with self.client.get("/advisory/did.json", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                # Validate it's a DID document
                if "@context" in data and "id" in data:
                    response.success()
                else:
                    response.failure("Invalid DID document structure")
            else:
                response.failure(f"DID document fetch returned {response.status_code}")


class AdvisoryRecordReportUser(AdvisoryAPIUser):
    """User that creates advisory reports via record_report endpoint.

    This is the main write operation for the Advisory API.
    """
    weight = 5
    wait_time = between(1.0, 3.0)

    @task
    def record_report(self):
        """POST /advisory/record_report"""
        payload = {
            "artefact_id": generate_uuid(),
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {
                "filename": f"report-{generate_uuid()[:8]}.xlsx",
                "service": "cca",
                "timestamp": "2026-02-23T09:00:00Z"
            },
            "provenance": []
        }

        with self.client.post(
            "/advisory/record_report",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                # Validate response structure
                if "artefact_did" in data and "version_did" in data and "version" in data:
                    # Store the artefact_id for potential future vc.json requests
                    if not hasattr(self, "created_artefacts"):
                        self.created_artefacts = []
                    self.created_artefacts.append(payload["artefact_id"])
                    response.success()
                else:
                    response.failure("Invalid record_report response structure")
            else:
                response.failure(f"record_report returned {response.status_code}")


class AdvisoryVCUser(AdvisoryAPIUser):
    """User that fetches Verifiable Credentials for advisory artefacts.

    Note: This requires artefacts to exist. In a real scenario, this would
    query pre-seeded data or data created by other users.
    """
    weight = 2
    wait_time = between(1.0, 3.0)

    def on_start(self):
        """Set up user and create an artefact for testing."""
        super().on_start()
        # Create an artefact to fetch VC for
        self.test_artefact_id = generate_uuid()
        payload = {
            "artefact_id": self.test_artefact_id,
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {"test": "data"},
            "provenance": []
        }
        response = self.client.post("/advisory/record_report", json=payload)
        if response.status_code != 200:
            print(f"Warning: Failed to create test artefact: {response.status_code}")

    @task
    def get_verifiable_credential(self):
        """GET /advisory/{uid}/vc.json"""
        with self.client.get(
            f"/advisory/{self.test_artefact_id}/vc.json",
            name="/advisory/{uid}/vc.json",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                # Validate it's a Verifiable Credential
                if "@context" in data and "type" in data and "credentialSubject" in data:
                    response.success()
                else:
                    response.failure("Invalid VC structure")
            else:
                response.failure(f"VC fetch returned {response.status_code}")


class AdvisoryMixedUser(AdvisoryAPIUser):
    """Mixed workload user for realistic Advisory API traffic patterns.

    Simulates a realistic mix of:
    - Creating reports (60%)
    - Fetching VCs (30%)
    - Fetching DID documents (10%)
    """
    weight = 3  # Higher weight allocates more users to this scenario
    wait_time = between(1.0, 3.0)

    def on_start(self):
        """Set up user and create initial artefact."""
        super().on_start()
        self.created_artefacts = []
        # Create initial artefact
        self._create_report()

    def _create_report(self):
        """Helper to create a report and store its ID."""
        artefact_id = generate_uuid()
        payload = {
            "artefact_id": artefact_id,
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {
                "filename": f"report-{artefact_id[:8]}.xlsx",
                "service": "cca"
            },
            "provenance": []
        }
        response = self.client.post("/advisory/record_report", json=payload)
        if response.status_code == 200:
            self.created_artefacts.append(artefact_id)

    @task(8)
    def record_report(self):
        """POST /advisory/record_report (60% weight)"""
        self._create_report()

    @task(2)
    def get_vc(self):
        """GET /advisory/{uid}/vc.json (30% weight)"""
        if self.created_artefacts:
            # Fetch VC for a previously created artefact
            import random
            artefact_id = random.choice(self.created_artefacts)
            self.client.get(f"/advisory/{artefact_id}/vc.json", name="/advisory/{uid}/vc.json")

    @task(1)
    def get_did_document(self):
        """GET /advisory/did.json (10% weight)"""
        self.client.get("/advisory/did.json")
