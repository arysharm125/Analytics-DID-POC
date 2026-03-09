"""Load testing scenarios for Advisory API endpoints.

Tests the following endpoints:
- GET /advisory/did.json (no auth)
- POST /advisory/record_report (requires token)
- GET /advisory/{uid}/vc.json (requires token)
"""
from common import AdvisoryAPIUser, BaseAPIUser, generate_multihash, generate_uuid
from locust import between, task


class AdvisoryDIDDocumentUser(BaseAPIUser):
    """User that fetches the Advisory division DID document.

    This is a public endpoint (no auth required).
    """
    weight = 20
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
    Reports now require a recommendation_uid reference.
    """
    weight = 500
    wait_time = between(1.0, 3.0)

    def on_start(self):
        """Set up user and create a recommendation for reports to reference."""
        super().on_start()
        # Create a recommendation that reports will reference
        rec_payload = {
            "recommendation_uid": generate_uuid(),
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {
                "recommendation_text": "Load test recommendation",
                "category": "testing"
            }
        }
        response = self.client.post("/advisory/record_recommendation", json=rec_payload)
        if response.status_code == 200:
            # Extract recommendation UID from DID
            self.recommendation_uid = response.json()["artefact_did"].split(":")[-1]
        else:
            print(f"Warning: Failed to create recommendation: {response.status_code}")
            self.recommendation_uid = generate_uuid()  # Fallback (will fail but allows test to continue)

    @task
    def record_report(self):
        """POST /advisory/record_report"""
        report_uid = generate_uuid()
        payload = {
            "report_uid": report_uid,
            "recommendation_uid": self.recommendation_uid,
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {
                "filename": f"report-{report_uid[:8]}.xlsx",
                "service": "cca",
                "timestamp": "2026-02-23T09:00:00Z"
            }
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
                    # Store the report_uid for potential future vc.json requests
                    if not hasattr(self, "created_artefacts"):
                        self.created_artefacts = []
                    self.created_artefacts.append(report_uid)
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
    weight = 200
    wait_time = between(1.0, 3.0)

    def on_start(self):
        """Set up user and create an artefact for testing."""
        super().on_start()
        # Create a recommendation first
        rec_payload = {
            "recommendation_uid": generate_uuid(),
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {"test": "recommendation"}
        }
        rec_response = self.client.post("/advisory/record_recommendation", json=rec_payload)
        if rec_response.status_code == 200:
            recommendation_uid = rec_response.json()["artefact_did"].split(":")[-1]
        else:
            print(f"Warning: Failed to create recommendation: {rec_response.status_code}")
            recommendation_uid = generate_uuid()

        # Create a report to fetch VC for
        self.test_report_uid = generate_uuid()
        payload = {
            "report_uid": self.test_report_uid,
            "recommendation_uid": recommendation_uid,
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {"test": "data"}
        }
        response = self.client.post("/advisory/record_report", json=payload)
        if response.status_code != 200:
            print(f"Warning: Failed to create test report: {response.status_code}")

    @task
    def get_verifiable_credential(self):
        """GET /advisory/{uid}/vc.json"""
        with self.client.get(
            f"/advisory/{self.test_report_uid}/vc.json",
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

    Reports are distributed across multiple recommendations to simulate realistic usage.
    """
    weight = 300  # Higher weight allocates more users to this scenario
    wait_time = between(1.0, 3.0)

    def on_start(self):
        """Set up user and create initial recommendations and reports."""
        super().on_start()
        self.created_recommendations = []
        self.created_reports = []

        # Create 2-3 initial recommendations
        import random
        num_recommendations = random.randint(2, 3)

        for _ in range(num_recommendations):
            self._create_recommendation()

        # Create initial reports
        for _ in range(2):
            self._create_report()

    def _create_recommendation(self):
        """Helper to create a recommendation and store its ID."""
        rec_uid = generate_uuid()
        rec_payload = {
            "recommendation_uid": rec_uid,
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {
                "recommendation_text": f"Recommendation {rec_uid[:8]}",
                "category": "testing"
            }
        }
        response = self.client.post("/advisory/record_recommendation", json=rec_payload)
        if response.status_code == 200:
            self.created_recommendations.append(rec_uid)

    def _create_report(self):
        """Helper to create a report and store its ID."""
        if not self.created_recommendations:
            return  # Skip if no recommendations available

        import random
        # Randomly select a recommendation to reference
        recommendation_uid = random.choice(self.created_recommendations)

        report_uid = generate_uuid()
        payload = {
            "report_uid": report_uid,
            "recommendation_uid": recommendation_uid,
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {
                "filename": f"report-{report_uid[:8]}.xlsx",
                "service": "cca"
            }
        }
        response = self.client.post("/advisory/record_report", json=payload)
        if response.status_code == 200:
            self.created_reports.append(report_uid)

    @task(8)
    def record_report(self):
        """POST /advisory/record_report (60% weight)"""
        self._create_report()

    @task(2)
    def get_vc(self):
        """GET /advisory/{uid}/vc.json (30% weight)"""
        if self.created_reports:
            # Fetch VC for a previously created report
            import random
            report_uid = random.choice(self.created_reports)
            self.client.get(f"/advisory/{report_uid}/vc.json", name="/advisory/{uid}/vc.json")

    @task(1)
    def get_did_document(self):
        """GET /advisory/did.json (10% weight)"""
        self.client.get("/advisory/did.json")
