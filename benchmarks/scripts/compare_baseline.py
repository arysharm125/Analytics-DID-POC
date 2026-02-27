#!/usr/bin/env python3
"""Compare current benchmark results against a baseline.

Usage:
    python benchmarks/scripts/compare_baseline.py --baseline <baseline.json> --current <current.json>

Examples:
    # Compare with default files
    python benchmarks/scripts/compare_baseline.py

    # Compare with specific baseline
    python benchmarks/scripts/compare_baseline.py \\
        --baseline benchmarks/baselines/1.1.0+abc123.json \\
        --current benchmarks/results/current.json

    # Set custom regression threshold (default 20%)
    python benchmarks/scripts/compare_baseline.py --threshold 0.30

Exit codes:
    0 - No regressions detected
    1 - Regressions detected
    2 - Error (missing files, etc.)
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Default configuration
DEFAULT_THRESHOLD = 0.20  # 20% regression threshold
DEFAULT_BASELINE = "benchmarks/baselines/main.json"
DEFAULT_CURRENT = "benchmarks/results/current.json"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Compare benchmark results against a baseline"
    )
    parser.add_argument(
        "--baseline", "-b",
        default=DEFAULT_BASELINE,
        help=f"Baseline JSON file (default: {DEFAULT_BASELINE})"
    )
    parser.add_argument(
        "--current", "-c",
        default=DEFAULT_CURRENT,
        help=f"Current results JSON file (default: {DEFAULT_CURRENT})"
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Regression threshold as decimal (default: {DEFAULT_THRESHOLD})"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed comparison for all endpoints"
    )
    return parser.parse_args()


def load_baseline(filepath: str) -> dict[str, Any]:
    """Load baseline JSON file.

    Args:
        filepath: Path to baseline JSON file

    Returns:
        Parsed baseline dict

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is invalid JSON
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Baseline file not found: {filepath}")

    with open(path) as f:
        return json.load(f)


def compare_endpoint(
    endpoint: str,
    baseline_stats: dict[str, float],
    current_stats: dict[str, float],
    threshold: float
) -> tuple[bool, dict[str, Any]]:
    """Compare statistics for a single endpoint.

    Args:
        endpoint: Endpoint name (e.g., "POST /advisory/record_report")
        baseline_stats: Baseline statistics dict
        current_stats: Current statistics dict
        threshold: Regression threshold (e.g., 0.20 for 20%)

    Returns:
        Tuple of (has_regression, comparison_dict)
    """
    metrics_to_check = ["p50_ms", "p95_ms", "p99_ms"]
    has_regression = False
    comparison = {
        "endpoint": endpoint,
        "metrics": {}
    }

    for metric in metrics_to_check:
        baseline_value = baseline_stats.get(metric, 0)
        current_value = current_stats.get(metric, 0)

        if baseline_value == 0:
            change_pct = 0.0
        else:
            change_pct = (current_value - baseline_value) / baseline_value

        is_regression = change_pct > threshold

        comparison["metrics"][metric] = {
            "baseline": baseline_value,
            "current": current_value,
            "change_pct": change_pct,
            "is_regression": is_regression
        }

        if is_regression:
            has_regression = True

    # Also track RPS (higher is better, so reverse the logic)
    baseline_rps = baseline_stats.get("rps", 0)
    current_rps = current_stats.get("rps", 0)
    if baseline_rps > 0:
        rps_change_pct = (current_rps - baseline_rps) / baseline_rps
        # Negative change in RPS is a regression
        is_rps_regression = rps_change_pct < -threshold
        comparison["metrics"]["rps"] = {
            "baseline": baseline_rps,
            "current": current_rps,
            "change_pct": rps_change_pct,
            "is_regression": is_rps_regression
        }
        if is_rps_regression:
            has_regression = True

    return has_regression, comparison


def print_comparison(comparison: dict[str, Any], verbose: bool = False):
    """Print formatted comparison results.

    Args:
        comparison: Comparison dict from compare_endpoint
        verbose: If True, show all metrics; if False, only show regressions
    """
    endpoint = comparison["endpoint"]
    metrics = comparison["metrics"]

    # Check if any regressions
    has_any_regression = any(m["is_regression"] for m in metrics.values())

    if not verbose and not has_any_regression:
        return

    # Print header
    symbol = "❌" if has_any_regression else "✓"
    print(f"\n{symbol} {endpoint}")

    # Print metrics
    for metric_name, data in metrics.items():
        baseline = data["baseline"]
        current = data["current"]
        change_pct = data["change_pct"]
        is_regression = data["is_regression"]

        # Format change percentage
        change_str = f"{change_pct:+.1%}"
        if is_regression:
            status = "⚠️  REGRESSION"
        elif abs(change_pct) < 0.05:  # Less than 5% change
            status = "≈ similar"
        elif change_pct < 0:
            status = "✓ improved"
        else:
            status = "↑ increased"

        print(f"  {metric_name:12s}: {baseline:8.1f} → {current:8.1f} ({change_str:>7s}) {status}")


def main():
    """Main entry point."""
    args = parse_args()

    # Load baseline and current results
    try:
        baseline = load_baseline(args.baseline)
        current = load_baseline(args.current)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(2)

    # Print header
    print("=" * 80)
    print("BENCHMARK COMPARISON")
    print("=" * 80)
    print(f"Baseline: {args.baseline} (version: {baseline.get('version', 'unknown')})")
    print(f"Current:  {args.current} (version: {current.get('version', 'unknown')})")
    print(f"Threshold: {args.threshold:.0%}")
    print("=" * 80)

    # Compare endpoints
    baseline_endpoints = baseline.get("endpoints", {})
    current_endpoints = current.get("endpoints", {})

    regressions_found = False
    comparisons = []

    # Check all endpoints in current results
    for endpoint, current_stats in current_endpoints.items():
        if endpoint not in baseline_endpoints:
            print(f"\n⚠️  New endpoint (no baseline): {endpoint}")
            continue

        baseline_stats = baseline_endpoints[endpoint]
        has_regression, comparison = compare_endpoint(
            endpoint, baseline_stats, current_stats, args.threshold
        )

        comparisons.append(comparison)
        if has_regression:
            regressions_found = True

    # Check for missing endpoints
    for endpoint in baseline_endpoints:
        if endpoint not in current_endpoints:
            print(f"\n⚠️  Missing endpoint (was in baseline): {endpoint}")

    # Print results
    for comparison in comparisons:
        print_comparison(comparison, verbose=args.verbose)

    # Summary
    print("\n" + "=" * 80)
    if regressions_found:
        print("❌ REGRESSIONS DETECTED")
        print(f"   Performance degraded beyond {args.threshold:.0%} threshold for one or more endpoints")
        print("=" * 80)
        sys.exit(1)
    else:
        print("✓ NO REGRESSIONS DETECTED")
        print(f"  All metrics within {args.threshold:.0%} threshold")
        print("=" * 80)
        sys.exit(0)


if __name__ == "__main__":
    main()
