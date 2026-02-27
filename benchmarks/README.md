# Performance Benchmarking Suite

Locust-based performance testing framework for the Analytics DID POC backend.

## Overview

This suite provides comprehensive load testing capabilities for the FastAPI backend, focusing on:
- **Latency measurement** (p50, p95, p99 percentiles)
- **Throughput measurement** (requests per second)
- **Version-to-version comparison** with regression detection
- **Git-tracked baselines** for historical tracking

## Quick Start

### 1. Start the Load Test Environment

```bash
# Start all services (API, MongoDB, Vault, Locust)
docker compose -f deployment/docker-compose.loadtest.yml up -d

# Verify services are running
docker compose -f deployment/docker-compose.loadtest.yml ps

# After finishing load testing
docker compose -f deployment/docker-compose.loadtest.yml down
```

Access Locust web UI: http://localhost:8433

### 2. Run Benchmarks

#### Option A: Interactive (Web UI)

1. Open http://localhost:8433
2. Configure:
   - Number of users: `50`
   - Spawn rate: `10`
   - Host: `http://nginx`
3. Click "Start swarming"
4. Monitor real-time results

#### Option B: Headless (CLI)

```bash
# Install dependencies (if running outside Docker)
pip install -r benchmarks/requirements.txt

# Quick sanity check run.
python benchmarks/scripts/run_benchmark.py --users 50 --duration 1m  --spawn-rate 5

# Run with default settings (50 users, 5 minutes)
python benchmarks/scripts/run_benchmark.py

# Custom configuration
python benchmarks/scripts/run_benchmark.py \
  --users 100 \
  --duration 10m \
  --spawn-rate 20
```

### 3. Export Baseline

```bash
# Save current results as baseline for this version
python benchmarks/scripts/export_baseline.py

# Commit to git
git add benchmarks/baselines/*.json
git commit -m "Add benchmark baseline for $(python benchmarks/version.py)"
```

### 4. Compare Against Baseline

```bash
# Compare current run against baseline
python benchmarks/scripts/compare_baseline.py \
  --baseline benchmarks/baselines/1.1.0+abc123.json \
  --current benchmarks/results/current.json

# Adjust regression threshold (default 20%)
python benchmarks/scripts/compare_baseline.py --threshold 0.30
```

## Directory Structure

```
benchmarks/
├── conftest.py                      # Data seeding hooks (stubs)
│
├── locustfiles/                     # Locust scenario definitions
│   ├── common.py                    # Shared user classes, utilities
│   ├── health_scenarios.py          # /health endpoint baseline
│   └── advisory_scenarios.py        # Advisory API scenarios
│
├── baselines/                       # Git-tracked baseline results
│   └── 1.1.0+e83d38.json           # Example baseline file
│
├── results/                         # Temporary test results (gitignored)
│   ├── current.json                # Latest run (JSON)
│   ├── run_20260223_*.csv          # Locust CSV exports
│   └── run_20260223_*.html         # Locust HTML reports
│
└── scripts/                         # Utility scripts
    ├── run_benchmark.py            # Run headless tests
    ├── compare_baseline.py         # Compare results
    └── export_baseline.py          # Save as baseline
```

## Test Scenarios

### Current Implementation (Advisory API)

| User Class | Endpoints Tested | Weight | Description |
|------------|------------------|--------|-------------|
| `HealthUser` | `GET /health` | N/A | Baseline reference (no auth, no DB) |
| `AdvisoryDIDDocumentUser` | `GET /advisory/did.json` | N/A | Public DID document fetch |
| `AdvisoryRecordReportUser` | `POST /advisory/record_report` | N/A | Create new reports |
| `AdvisoryVCUser` | `GET /advisory/{uid}/vc.json` | N/A | Fetch verifiable credentials |
| `AdvisoryMixedUser` | All advisory endpoints | 60/30/10 | Realistic mixed workload |

### Future: EPDW Scenarios (TODO)

- `POST /create-sut-did`
- `POST /append-did`
- `GET /epdw/{uid}/vc.json`

## Configuration

### Default Test Parameters

```python
DEFAULT_USERS = 50           # Concurrent users
DEFAULT_SPAWN_RATE = 10      # Users spawned per second
DEFAULT_DURATION = "5m"      # Test duration
REGRESSION_THRESHOLD = 0.20  # 20% regression threshold
```

### Environment Variables

Set in `.env.loadtest` or Docker Compose:

```bash
ADVISORY_API_TOKEN=test-advisory-token
EPDW_API_TOKEN=test-epdw-token
```

**Note:** Vault secrets are automatically initialized by the `vault-init` service on startup. MongoDB connection details are stored at `secret/mongo` in the Vault dev server.

## Baseline File Format

Baselines are JSON files with the following structure:

```json
{
  "version": "1.1.0+e83d38",
  "timestamp": "2026-02-23T12:30:00Z",
  "environment": {
    "type": "docker-local",
    "host": "http://localhost:8432"
  },
  "test_config": {
    "users": 50,
    "spawn_rate": 10,
    "duration": "5m"
  },
  "endpoints": {
    "GET /health": {
      "requests": 5000,
      "failures": 0,
      "p50_ms": 2.1,
      "p95_ms": 5.4,
      "p99_ms": 9.2,
      "rps": 125.3
    }
  }
}
```

## Regression Detection

The comparison script checks for performance regressions in:

1. **Latency metrics** (higher is worse):
   - p50, p95, p99 response times
   - Regression = increase > threshold (default 20%)

2. **Throughput metrics** (lower is worse):
   - RPS (requests per second)
   - Regression = decrease > threshold

### Exit Codes

```bash
0 - No regressions detected
1 - Regressions detected
2 - Error (missing files, invalid JSON, etc.)
```

### Example Output

```
================================================================================
BENCHMARK COMPARISON
================================================================================
Baseline: benchmarks/baselines/1.1.0+abc123.json (version: 1.1.0+abc123)
Current:  benchmarks/results/current.json (version: 1.1.0+def456)
Threshold: 20%
================================================================================

❌ POST /advisory/record_report
  p50_ms      :     45.2 →     58.7 (+29.9%) ⚠️  REGRESSION
  p95_ms      :    112.5 →    145.3 (+29.2%) ⚠️  REGRESSION
  p99_ms      :    198.3 →    210.5 ( +6.1%) ↑ increased
  rps         :     22.5 →     18.2 (-19.1%) ≈ similar

✓ GET /advisory/did.json
  p50_ms      :      3.1 →      3.2 ( +3.2%) ≈ similar
  p95_ms      :      8.5 →      8.9 ( +4.7%) ≈ similar

================================================================================
❌ REGRESSIONS DETECTED
   Performance degraded beyond 20% threshold for one or more endpoints
================================================================================
```

## Troubleshooting

### Issue: Locust import errors

```bash
# Install dependencies
pip install -r benchmarks/requirements.txt

# Or use Docker (recommended)
docker compose -f deployment/docker-compose.loadtest.yml up
```

### Issue: Connection refused

```bash
# Ensure services are running
docker compose -f deployment/docker-compose.loadtest.yml ps

# Check API health
curl http://localhost:8432/health
```

### Issue: High failure rates

```bash
# Check API logs
docker compose -f deployment/docker-compose.loadtest.yml logs api

# Reduce load
python benchmarks/scripts/run_benchmark.py --users 10 --spawn-rate 2
```

### Issue: Version mismatch

```bash
# Verify git version
python benchmarks/version.py

# Should output: 1.1.0+abc123 (or similar)
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Performance Tests

on:
  pull_request:
    branches: [main]

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Start test environment
        run: |
          docker compose -f deployment/docker-compose.loadtest.yml up -d
          sleep 10  # Wait for services to be ready

      - name: Run benchmarks
        run: |
          pip install -r benchmarks/requirements.txt
          python benchmarks/scripts/run_benchmark.py --duration 2m

      - name: Compare against baseline
        run: |
          python benchmarks/scripts/compare_baseline.py \
            --baseline benchmarks/baselines/main.json \
            --threshold 0.20
```

## Best Practices

### 1. Baseline Management

- Create baselines for each release version
- Commit baselines to git for historical tracking
- Use `main.json` for continuous comparison against main branch

### 2. Test Duration

- **Quick validation**: 1-2 minutes
- **Standard testing**: 5 minutes (default)
- **Soak testing**: 30+ minutes (detect memory leaks)

### 3. Load Levels

- **Smoke test**: 1-5 users
- **Standard load**: 50 users (default)
- **Stress test**: 100-500 users (find breaking point)

### 4. Version Naming

- Baselines automatically use `VERSION+gitsha` format
- Example: `1.1.0+e83d38.json`
- Ensures unique identification per commit

## Future Enhancements

- [ ] Add EPDW scenarios (create-sut-did, append-did)
- [ ] Implement data seeding for read-heavy tests
- [ ] Add Prometheus metrics export
- [ ] Create Grafana dashboards
- [ ] Add distributed testing (multiple Locust workers)
- [ ] Implement soak test scenarios
- [ ] Add spike test scenarios

## Contributing

When adding new benchmark scenarios:

1. Create a new user class in `locustfiles/`
2. Use appropriate base class (`BaseAPIUser`, `AdvisoryAPIUser`, etc.)
3. Add `@task` decorators with optional weights
4. Update this README with the new scenario

## Support

For issues or questions:
- Check `docker compose logs` for service errors
- Review Locust HTML reports in `benchmarks/results/`
- Consult Locust documentation: https://docs.locust.io/
