"""Load testing scenarios for EPDW API endpoints.

Tests the following endpoints:
- GET /epdw/did.json (no auth)
- POST /epdw/record-benchmark (requires token)
- POST /epdw/update-multiple-artefacts (requires token)
- GET /epdw/{uid}/vc.json (requires token)
"""
from common import BaseAPIUser, EPDWAPIUser, generate_multihash, generate_uuid
from locust import between, task


class EPDWDIDDocumentUser(BaseAPIUser):
    """User that fetches the EPDW division DID document.

    This is a public endpoint (no auth required).
    """
    weight = 20
    wait_time = between(0.5, 2.0)

    @task
    def get_did_document(self):
        """GET /epdw/did.json"""
        with self.client.get("/epdw/did.json", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                # Validate it's a DID document
                if "@context" in data and "id" in data:
                    response.success()
                else:
                    response.failure("Invalid DID document structure")
            else:
                response.failure(f"DID document fetch returned {response.status_code}")


class EPDWRecordBenchmarkUser(EPDWAPIUser):
    """User that records benchmarks with iterations via record-benchmark endpoint.

    This is the main write operation for the EPDW API.
    """
    weight = 500
    wait_time = between(1.0, 3.0)

    @task
    def record_benchmark(self):
        """POST /epdw/record-benchmark"""
        import random

        benchmark_id = generate_uuid()
        num_iterations = random.randint(1, 3)  # 1-3 iterations per benchmark

        iterations = []
        for i in range(num_iterations):
            iterations.append({
                "iteration_id": generate_uuid(),
                "artefact_hash": generate_multihash(),
                "artefact_metadata": {
                    "run": i + 1,
                    "score": round(random.uniform(100, 500), 2),
                    "runtime_seconds": random.randint(60, 600)
                }
            })

        payload = {
            "benchmark_id": benchmark_id,
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {
                "name": "SPEC CPU 2017",
                "config": "base",
                "system": f"EPYC-{benchmark_id[:8]}"
            },
            "iterations": iterations
        }

        with self.client.post(
            "/epdw/record-benchmark",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                # Validate response structure
                if ("benchmark_did" in data and "benchmark_version_did" in data
                    and "iterations" in data and "partial_failure" in data):
                    # Store created artefact IDs for potential future use
                    if not hasattr(self, "created_benchmarks"):
                        self.created_benchmarks = []
                    self.created_benchmarks.append(benchmark_id)

                    # Also store iteration IDs
                    if not hasattr(self, "created_iterations"):
                        self.created_iterations = []
                    for iteration in data["iterations"]:
                        if iteration["status"] != "error":
                            self.created_iterations.append(iteration["iteration_id"])

                    response.success()
                else:
                    response.failure("Invalid record_benchmark response structure")
            else:
                response.failure(f"record_benchmark returned {response.status_code}")


class EPDWUpdateArtefactsUser(EPDWAPIUser):
    """User that updates existing artefacts via update-multiple-artefacts endpoint.

    Note: This requires artefacts to exist. Creates initial benchmarks, then updates them.
    """
    weight = 300
    wait_time = between(1.0, 3.0)

    def on_start(self):
        """Set up user and create initial artefacts for testing."""
        super().on_start()
        self.artefact_ids = []

        # Create 2-3 initial benchmarks to update later
        import random
        num_benchmarks = random.randint(2, 3)

        for _ in range(num_benchmarks):
            benchmark_id = generate_uuid()
            payload = {
                "benchmark_id": benchmark_id,
                "artefact_hash": generate_multihash(),
                "artefact_metadata": {"initial": "data"},
                "iterations": [
                    {
                        "iteration_id": generate_uuid(),
                        "artefact_hash": generate_multihash(),
                        "artefact_metadata": {"run": 1}
                    }
                ]
            }

            response = self.client.post("/epdw/record-benchmark", json=payload)
            if response.status_code == 200:
                data = response.json()
                # Collect both benchmark and iteration IDs
                self.artefact_ids.append(benchmark_id)
                for iteration in data["iterations"]:
                    if iteration["status"] != "error":
                        self.artefact_ids.append(iteration["iteration_id"])

    @task
    def update_multiple_artefacts(self):
        """POST /epdw/update-multiple-artefacts"""
        if not self.artefact_ids:
            return  # Skip if no artefacts available

        import random

        # Update 1-2 artefacts
        num_updates = min(random.randint(1, 2), len(self.artefact_ids))
        artefacts_to_update = random.sample(self.artefact_ids, num_updates)

        updates = []
        for artefact_id in artefacts_to_update:
            updates.append({
                "external_uid": artefact_id,
                "artefact_hash": generate_multihash(),
                "artefact_metadata": {
                    "updated": True,
                    "timestamp": "2026-03-03T09:00:00Z",
                    "score": round(random.uniform(100, 500), 2)
                }
            })

        payload = {"updates": updates}

        with self.client.post(
            "/epdw/update-multiple-artefacts",
            json=payload,
            name="/epdw/update-multiple-artefacts",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                # Validate response structure
                if "results" in data and "partial_failure" in data:
                    response.success()
                else:
                    response.failure("Invalid update response structure")
            else:
                response.failure(f"update returned {response.status_code}")


class EPDWVCUser(EPDWAPIUser):
    """User that fetches Verifiable Credentials for EPDW artefacts.

    Note: This requires artefacts to exist. Creates an initial benchmark, then fetches its VC.
    """
    weight = 200
    wait_time = between(1.0, 3.0)

    def on_start(self):
        """Set up user and create an artefact for testing."""
        super().on_start()

        # Create a benchmark with one iteration
        self.test_benchmark_id = generate_uuid()
        self.test_iteration_id = generate_uuid()

        payload = {
            "benchmark_id": self.test_benchmark_id,
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {"test": "vc_user"},
            "iterations": [
                {
                    "iteration_id": self.test_iteration_id,
                    "artefact_hash": generate_multihash(),
                    "artefact_metadata": {"run": 1}
                }
            ]
        }

        response = self.client.post("/epdw/record-benchmark", json=payload)
        if response.status_code != 200:
            print(f"Warning: Failed to create test benchmark: {response.status_code}")

    @task
    def get_benchmark_vc(self):
        """GET /epdw/{uid}/vc.json for benchmark"""
        with self.client.get(
            f"/epdw/{self.test_benchmark_id}/vc.json",
            name="/epdw/{uid}/vc.json (benchmark)",
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

    @task
    def get_iteration_vc(self):
        """GET /epdw/{uid}/vc.json for iteration"""
        with self.client.get(
            f"/epdw/{self.test_iteration_id}/vc.json",
            name="/epdw/{uid}/vc.json (iteration)",
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


class EPDWMixedUser(EPDWAPIUser):
    """Mixed workload user for realistic EPDW API traffic patterns.

    Simulates a realistic mix of:
    - Recording benchmarks (60%)
    - Updating artefacts (20%)
    - Fetching VCs (10%)
    - Fetching DID documents (10%)
    """
    weight = 300  # Higher weight allocates more users to this scenario
    wait_time = between(1.0, 3.0)

    def on_start(self):
        """Set up user and create initial artefacts."""
        super().on_start()
        self.created_benchmarks = []
        self.created_iterations = []

        # Create initial benchmarks
        for _ in range(2):
            self._create_benchmark()

    def _create_benchmark(self):
        """Helper to create a benchmark and store its IDs."""
        import random

        benchmark_id = generate_uuid()
        num_iterations = random.randint(1, 2)

        iterations = []
        iteration_ids = []
        for i in range(num_iterations):
            iteration_id = generate_uuid()
            iteration_ids.append(iteration_id)
            iterations.append({
                "iteration_id": iteration_id,
                "artefact_hash": generate_multihash(),
                "artefact_metadata": {
                    "run": i + 1,
                    "score": round(random.uniform(100, 500), 2)
                }
            })

        payload = {
            "benchmark_id": benchmark_id,
            "artefact_hash": generate_multihash(),
            "artefact_metadata": {
                "name": "Mixed workload benchmark",
                "timestamp": "2026-03-03T09:00:00Z"
            },
            "iterations": iterations
        }

        response = self.client.post("/epdw/record-benchmark", json=payload)
        if response.status_code == 200:
            self.created_benchmarks.append(benchmark_id)
            self.created_iterations.extend(iteration_ids)

    @task(6)
    def record_benchmark(self):
        """POST /epdw/record-benchmark (60% weight)"""
        self._create_benchmark()

    @task(2)
    def update_artefacts(self):
        """POST /epdw/update-multiple-artefacts (20% weight)"""
        if not (self.created_benchmarks or self.created_iterations):
            return  # Skip if no artefacts available

        import random

        # Combine all available artefacts
        all_artefacts = self.created_benchmarks + self.created_iterations

        # Update 1-2 artefacts
        num_updates = min(random.randint(1, 2), len(all_artefacts))
        artefacts_to_update = random.sample(all_artefacts, num_updates)

        updates = []
        for artefact_id in artefacts_to_update:
            updates.append({
                "external_uid": artefact_id,
                "artefact_hash": generate_multihash(),
                "artefact_metadata": {
                    "updated": True,
                    "score": round(random.uniform(100, 500), 2)
                }
            })

        payload = {"updates": updates}
        self.client.post("/epdw/update-multiple-artefacts", json=payload)

    @task(1)
    def get_vc(self):
        """GET /epdw/{uid}/vc.json (10% weight)"""
        if self.created_benchmarks or self.created_iterations:
            # Fetch VC for a previously created artefact
            import random
            all_artefacts = self.created_benchmarks + self.created_iterations
            artefact_id = random.choice(all_artefacts)
            self.client.get(f"/epdw/{artefact_id}/vc.json", name="/epdw/{uid}/vc.json")

    @task(1)
    def get_did_document(self):
        """GET /epdw/did.json (10% weight)"""
        self.client.get("/epdw/did.json")
