"""Shared pytest fixtures and data seeding utilities for benchmarks.

This module provides stubs for data seeding that can be implemented
when needed for more complex benchmark scenarios.
"""
from typing import List


def seed_advisory_data(db_url: str, count: int = 100) -> List[str]:
    """Pre-populate MongoDB with advisory artefacts for read testing.

    This is a stub for future implementation when read-heavy scenarios
    are added (e.g., benchmarking VC fetching with pre-seeded data).

    Args:
        db_url: MongoDB connection URL
        count: Number of artefacts to create

    Returns:
        List of artefact UIDs that can be used in benchmark scenarios

    Raises:
        NotImplementedError: This is a stub, not yet implemented
    """
    raise NotImplementedError(
        "Data seeding not yet implemented. "
        "For now, advisory benchmarks create their own test data on-the-fly."
    )


def seed_epdw_data(db_url: str, benchmark_count: int = 10) -> dict:
    """Pre-populate MongoDB with EPDW benchmark executions and iterations.

    This is a stub for future implementation when EPDW scenarios are added.

    Args:
        db_url: MongoDB connection URL
        benchmark_count: Number of benchmark executions to create

    Returns:
        Dict mapping benchmark IDs to their iteration IDs

    Raises:
        NotImplementedError: This is a stub, not yet implemented
    """
    raise NotImplementedError(
        "EPDW data seeding not yet implemented. "
        "Will be added when EPDW benchmark scenarios are created."
    )


def get_test_artefact_uids() -> List[str]:
    """Return list of artefact UIDs for vc.json endpoint testing.

    For now, returns empty list since advisory scenarios create their own data.

    Returns:
        Empty list (stub implementation)
    """
    return []


def clear_benchmark_data(db_url: str) -> None:
    """Clear all benchmark-generated data from MongoDB.

    This is a stub for future implementation to clean up after load tests.

    Args:
        db_url: MongoDB connection URL

    Raises:
        NotImplementedError: This is a stub, not yet implemented
    """
    raise NotImplementedError(
        "Data cleanup not yet implemented. "
        "Manually drop the loadtest database if needed."
    )
