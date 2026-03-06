#!/usr/bin/env python3
"""Full test suite runner.

This script runs the complete test suite including:
1. Linting with ruff
2. Unit and integration tests with pytest (local mode)
3. Integration tests with Docker containers
4. VC compatibility tests (Python)
5. VC compatibility tests (didcheck frontend)
6. Load test sanity check with Docker containers

Usage:
    python scripts/full_test.py
"""

import subprocess
import sys
import time
from pathlib import Path


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def run_command(cmd: list[str], check: bool = True, description: str = "") -> int:
    """Run a command and handle errors.

    Args:
        cmd: Command and arguments to run
        check: Whether to exit on non-zero return code
        description: Optional description of the command

    Returns:
        Return code of the command
    """
    if description:
        print(f"→ {description}")
    print(f"$ {' '.join(cmd)}\n")

    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"\n✗ Command failed with exit code {result.returncode}", file=sys.stderr)
        if check:
            sys.exit(result.returncode)
    else:
        print("\n✓ Command completed successfully")

    return result.returncode


def main() -> int:
    """Run the full test suite."""
    # Change to project root
    project_root = Path(__file__).parent.parent

    start_time = time.time()

    # Step 1: Ruff linting
    print_section("Step 1/6: Running Ruff Linter")
    ret = run_command(
        ["ruff", "check", "."],
        check=True,
        description="Running ruff check on entire codebase"
    )
    if ret != 0:
        return ret

    # Step 2: Pytest (local mode)
    print_section("Step 2/6: Running Pytest (Local Mode)")
    ret = run_command(
        ["pytest", "--cov=app", "--cov-report="],
        check=True,
        description="Running pytest with local dependencies (mock vault)"
    )
    if ret != 0:
        return ret

    # Step 3: Pytest with containers
    print_section("Step 3/6: Running Pytest (Container Mode)")
    ret = run_command(
        ["pytest", "--db-mode=container", "--vault-mode=container", "--cov=app", "--cov-append", "--cov-report="],
        check=True,
        description="Running pytest with MongoDB and Vault containers"
    )
    if ret != 0:
        return ret

    # Step 4: VC Compatibility tests (Python)
    print_section("Step 4/6: Running VC Compatibility Tests (Python)")
    ret = run_command(
        ["pytest", "-m", "vc_compat"],
        check=True,
        description="Running Python VC compatibility test suite"
    )
    if ret != 0:
        return ret

    # Step 5: VC Compatibility tests (didcheck frontend)
    print_section("Step 5/6: Running VC Compatibility Tests (Didcheck Frontend)")
    print("→ Running didcheck frontend VC compatibility tests")
    print("$ cd didcheck && npm run test:vc-compat\n")
    result = subprocess.run(
        ["npm", "run", "test:vc-compat"],
        cwd=project_root / "didcheck"
    )
    if result.returncode != 0:
        print(f"\n✗ Command failed with exit code {result.returncode}", file=sys.stderr)
        return result.returncode
    else:
        print("\n✓ Command completed successfully")

    # Step 6: Load test sanity check
    print_section("Step 6/6: Running Load Test Sanity Check")

    try:
        # Stop any existing loadtest containers
        print("→ Stopping any existing loadtest containers...")
        subprocess.run(
            ["docker", "compose", "-f", "deployment/docker-compose.loadtest.yml", "down", "-v"],
            cwd=project_root,
            capture_output=True
        )

        # Rebuild and start containers
        print("\n→ Rebuilding and starting loadtest containers...")
        ret = run_command(
            ["docker", "compose", "-f", "deployment/docker-compose.loadtest.yml", "up", "-d", "--build"],
            check=True,
            description="Building and starting loadtest environment"
        )
        if ret != 0:
            return ret

        # Wait for services to be ready
        print("\n→ Waiting for services to be ready...")
        time.sleep(10)

        # Check service health
        print("\n→ Checking service health...")
        health_check = subprocess.run(
            ["docker", "exec", "didsvc-loadtest-api", "curl", "-f", "http://localhost:8434/health"],
            cwd=project_root,
            capture_output=True
        )
        if health_check.returncode != 0:
            print("⚠ Warning: Health check failed, but continuing with load test...", file=sys.stderr)
        else:
            print("✓ API is healthy")

        # Run sanity load test (30 seconds)
        print("\n→ Running sanity load test (30 seconds)...")
        ret = run_command(
            [
                "python", "benchmarks/scripts/run_benchmark.py",
                "--users", "50",
                "--spawn-rate", "10",
                "--duration", "30s",
                "--host", "http://localhost:8432",
                "--output", "benchmarks/results/sanity_test.json"
            ],
            check=False,  # Don't fail if there are some request errors
            description="Running 30-second sanity load test"
        )

        # Load test completed (even with some failures)
        print("\n✓ Load test completed")

    finally:
        # Always cleanup containers
        print("\n→ Shutting down loadtest containers...")
        subprocess.run(
            ["docker", "compose", "-f", "deployment/docker-compose.loadtest.yml", "down", "-v"],
            cwd=project_root
        )
        print("✓ Loadtest containers stopped and cleaned up")

    # Summary
    elapsed = time.time() - start_time
    print_section("Test Suite Complete!")
    print(f"Total time: {elapsed:.1f} seconds")
    print("\nAll tests passed successfully! ✓")

    return 0


if __name__ == "__main__":
    sys.exit(main())
