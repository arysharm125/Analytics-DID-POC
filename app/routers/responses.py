"""Reusable response documentation for FastAPI endpoints."""


def not_found_response(
    resource: str = "Artefact",
    example_detail: str | None = None,
) -> dict:
    """
    Generate 404 Not Found response documentation.

    Args:
        resource: The type of resource (e.g., "Artefact", "Benchmark")
        example_detail: Optional custom detail message for the example

    Returns:
        FastAPI response documentation dict for 404 errors
    """
    if example_detail is None:
        example_detail = f"{resource} with uid 'b8ff3b79-863f-4fa9-84ba-0067663f2b04' not found in any division"

    return {
        404: {
            "description": f"{resource} not found",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": f"{resource} not found",
                            "value": {"detail": example_detail}
                        }
                    }
                }
            },
        }
    }


def conflict_response(division: str = "division") -> dict:
    """
    Generate 409 Conflict response documentation.

    Args:
        division: The division name to use in examples (e.g., "advisory", "epdw")

    Returns:
        FastAPI response documentation dict for 409 errors
    """
    return {
        409: {
            "description": "Conflict error: Division mismatch or version conflict",
            "content": {
                "application/json": {
                    "examples": {
                        "division_mismatch": {
                            "summary": "Division mismatch",
                            "value": {
                                "detail": f"Division mismatch: existing division is '{division}', but attempted to set 'other'"
                            }
                        },
                        "version_conflict": {
                            "summary": "Version conflict",
                            "value": {"detail": "Version conflict: version 2 already exists"}
                        },
                        "provenance_not_found": {
                            "summary": "Provenance item not found",
                            "value": {"detail": "Provenance item not found: 2cacad4f-63ab-4668-9db7-7fc2538caa8c"}
                        }
                    }
                }
            }
        }
    }


def bad_request_response() -> dict:
    """
    Generate 400 Bad Request response documentation.

    Returns:
        FastAPI response documentation dict for 400 errors
    """
    return {
        400: {
            "description": "Bad Request: Invalid input or no changes detected",
            "content": {
                "application/json": {
                    "examples": {
                        "no_changes": {
                            "summary": "No changes detected",
                            "value": {
                                "detail": (
                                    "No changes detected for artefact 'b8ff3b79-863f-4fa9-84ba-0067663f2b04'. "
                                    "A new version requires changes to at least one of: "
                                    "artefact_hash, artefact_metadata, or provenance."
                                )
                            }
                        },
                        "duplicate_provenance": {
                            "summary": "Duplicated item in provenance list",
                            "value": {
                                "detail": (
                                    "Duplicate identifiers found after canonicalization. "
                                    "Each provenance item must be unique."
                                )
                            }
                        },
                        "duplicate_iteration_ids": {
                            "summary": "Duplicate iteration IDs",
                            "value": {"detail": "Duplicate iteration IDs found: iter-1, iter-2"}
                        },
                        "empty_iterations": {
                            "summary": "Empty iterations list",
                            "value": {"detail": "At least one iteration is required"}
                        }
                    }
                }
            }
        }
    }
