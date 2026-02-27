#!/usr/bin/env python3
"""Export current benchmark results as a new baseline.

This script copies the current benchmark results to the baselines directory
with a filename based on the version string (e.g., 1.1.0+e83d38.json).

Usage:
    python benchmarks/scripts/export_baseline.py [options]

Examples:
    # Export current.json as new baseline
    python benchmarks/scripts/export_baseline.py

    # Export specific results file
    python benchmarks/scripts/export_baseline.py --input benchmarks/results/my_test.json

    # Force overwrite if baseline already exists
    python benchmarks/scripts/export_baseline.py --force
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

DEFAULT_INPUT = "benchmarks/results/current.json"
BASELINES_DIR = "benchmarks/baselines"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Export current benchmark results as a new baseline"
    )
    parser.add_argument(
        "--input", "-i",
        default=DEFAULT_INPUT,
        help=f"Input JSON file to export (default: {DEFAULT_INPUT})"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing baseline if it exists"
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Load input file
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(input_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in input file: {e}", file=sys.stderr)
        sys.exit(1)

    # Get version from data
    version = data.get("version")
    if not version:
        print("Error: Input file missing 'version' field", file=sys.stderr)
        sys.exit(1)

    # Create baselines directory if it doesn't exist
    baselines_path = Path(BASELINES_DIR)
    baselines_path.mkdir(parents=True, exist_ok=True)

    # Determine output filename
    output_path = baselines_path / f"{version}.json"

    # Check if baseline already exists
    if output_path.exists() and not args.force:
        print(f"Error: Baseline already exists: {output_path}", file=sys.stderr)
        print("Use --force to overwrite", file=sys.stderr)
        sys.exit(1)

    # Copy file
    shutil.copy2(input_path, output_path)

    print("✓ Baseline exported successfully!")
    print(f"  Version: {version}")
    print(f"  File: {output_path}")
    print("\nTo use this baseline for comparisons:")
    print(f"  python benchmarks/scripts/compare_baseline.py --baseline {output_path}")
    print("\nTo commit this baseline to git:")
    print(f"  git add {output_path}")
    print(f"  git commit -m 'Add benchmark baseline for {version}'")


if __name__ == "__main__":
    main()
