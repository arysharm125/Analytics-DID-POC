#!/usr/bin/env python3
"""Run Locust benchmark headless and export results to JSON.

Usage:
    python benchmarks/scripts/run_benchmark.py [options]

Examples:
    # Run with defaults (50 users, 5 minutes)
    python benchmarks/scripts/run_benchmark.py

    # Custom parameters
    python benchmarks/scripts/run_benchmark.py --users 100 --duration 10m --spawn-rate 20

    # Save to specific output file
    python benchmarks/scripts/run_benchmark.py --output benchmarks/results/my_test.json
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import csv

# Add parent directory to path to import version module
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from app.version import full_version


# Default test configuration
DEFAULT_USERS = 50
DEFAULT_SPAWN_RATE = 10
DEFAULT_DURATION = "5m"
DEFAULT_HOST = "http://localhost:8432"
DEFAULT_LOCUSTFILE = "locustfiles"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run Locust benchmark and export results to JSON"
    )
    parser.add_argument(
        "--users", "-u",
        type=int,
        default=DEFAULT_USERS,
        help=f"Number of concurrent users (default: {DEFAULT_USERS})"
    )
    parser.add_argument(
        "--spawn-rate", "-r",
        type=int,
        default=DEFAULT_SPAWN_RATE,
        help=f"Users spawned per second (default: {DEFAULT_SPAWN_RATE})"
    )
    parser.add_argument(
        "--duration", "-t",
        default=DEFAULT_DURATION,
        help=f"Test duration (e.g., 5m, 30s) (default: {DEFAULT_DURATION})"
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Target host URL (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--locustfile", "-f",
        default=DEFAULT_LOCUSTFILE,
        help=f"Locust file or directory to run (default: {DEFAULT_LOCUSTFILE})"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file path (default: benchmarks/results/current.json)"
    )
    return parser.parse_args()


def run_locust(users, spawn_rate, duration, host, locustfile):
    """Run Locust in headless mode and capture CSV output.

    Returns:
        Path to the CSV stats file
    """
    # Create results directory
    results_dir = Path(__file__).parent.parent / "results"
    results_dir.mkdir(exist_ok=True)

    # Generate timestamp-based CSV prefix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_prefix = results_dir / f"run_{timestamp}"

    # Run Locust
    cmd = [
        "locust",
        "-f", locustfile,
        "--headless",
        "-u", str(users),
        "-r", str(spawn_rate),
        "--run-time", duration,
        "--host", host,
        "--csv", str(csv_prefix),
        "--html", f"{csv_prefix}_report.html",
    ]

    print(f"Running Locust: {' '.join(cmd)}")
    print(f"Test parameters: {users} users, {spawn_rate}/sec spawn rate, {duration} duration")
    print(f"Target: {host}")
    print("-" * 80)

    # Run Locust without check=True to allow processing results even when there are failures
    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent)

    if result.returncode != 0:
        print(f"\n⚠ Warning: Locust reported failures (exit code {result.returncode})", file=sys.stderr)
        print("Continuing to process results...", file=sys.stderr)

    # Verify that CSV stats file was actually created
    stats_file = Path(f"{csv_prefix}_stats.csv")
    if not stats_file.exists():
        print(f"\n✗ Error: Stats file not generated at {stats_file}", file=sys.stderr)
        print("This indicates Locust failed to run properly.", file=sys.stderr)
        sys.exit(1)

    return csv_prefix


def parse_locust_stats(csv_prefix):
    """Parse Locust CSV output and return structured data.

    Args:
        csv_prefix: Path prefix for CSV files (without extension)

    Returns:
        dict with endpoint statistics
    """
    stats_file = Path(f"{csv_prefix}_stats.csv")

    if not stats_file.exists():
        raise FileNotFoundError(f"Stats file not found: {stats_file}")

    endpoints = {}

    with open(stats_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip aggregated rows
            if row['Type'] == 'Aggregated' or row['Name'] == 'Aggregated':
                continue

            # Extract endpoint name and method
            name = row['Name']
            method = row['Type']

            # Parse metrics
            endpoints[f"{method} {name}"] = {
                "requests": int(row['Request Count']),
                "failures": int(row['Failure Count']),
                "p50_ms": float(row['50%']),
                "p95_ms": float(row['95%']),
                "p99_ms": float(row['99%']),
                "average_ms": float(row['Average Response Time']),
                "min_ms": float(row['Min Response Time']),
                "max_ms": float(row['Max Response Time']),
                "rps": float(row['Requests/s']),
            }

    return endpoints


def create_baseline_json(args, endpoints):
    """Create baseline JSON structure.

    Args:
        args: Parsed command line arguments
        endpoints: Dict of endpoint statistics

    Returns:
        dict with full baseline structure
    """
    return {
        "version": full_version(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "type": "docker-local",
            "host": args.host,
        },
        "test_config": {
            "users": args.users,
            "spawn_rate": args.spawn_rate,
            "duration": args.duration,
            "locustfile": args.locustfile,
        },
        "endpoints": endpoints
    }


def main():
    """Main entry point."""
    args = parse_args()

    # Run Locust and get CSV output
    csv_prefix = run_locust(
        args.users,
        args.spawn_rate,
        args.duration,
        args.host,
        args.locustfile
    )

    # Parse results
    print("\nParsing results...")
    endpoints = parse_locust_stats(csv_prefix)

    # Create baseline JSON
    baseline = create_baseline_json(args, endpoints)

    # Determine output file
    if args.output:
        output_file = Path(args.output)
    else:
        output_file = Path(__file__).parent.parent / "results" / "current.json"

    # Ensure output directory exists
    output_file.parent.mkdir(exist_ok=True)

    # Write JSON
    with open(output_file, 'w') as f:
        json.dump(baseline, f, indent=2)

    print(f"\n✓ Benchmark complete!")
    print(f"  Results saved to: {output_file}")
    print(f"  HTML report: {csv_prefix}_report.html")
    print(f"\nKey metrics:")
    for endpoint, stats in endpoints.items():
        print(f"  {endpoint}:")
        print(f"    RPS: {stats['rps']:.1f}, p95: {stats['p95_ms']:.1f}ms, errors: {stats['failures']}")


if __name__ == "__main__":
    main()
