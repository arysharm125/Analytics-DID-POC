"""Deep comparison utilities for nested data structures.

This module provides functions for comparing nested dicts, lists, and primitives,
supporting both detailed diff computation and efficient equality checks.
"""
from typing import Any, Dict, Union, cast


def compute_diff(
    old: Any,
    new: Any,
    path: str = "",
    early_exit: bool = False,
) -> Union[Dict[str, Any], bool]:
    """Compute the difference between two values.

    Recursively compares nested dicts, lists, and primitives to identify
    additions, removals, and modifications.

    Args:
        old: The old value to compare
        new: The new value to compare
        path: Current path for nested keys (used internally for recursion)
        early_exit: If True, return True immediately when any difference is found
                   (used for efficient equality checks). If False, compute full diff.

    Returns:
        If early_exit=False: dict with 'added', 'removed', 'modified' keys,
            each containing path -> {"old": ..., "new": ...} mappings
        If early_exit=True: True if any difference found, False if equal
    """
    # Initialize diff structure (only used when early_exit=False)
    if not early_exit:
        diff: Dict[str, Dict[str, Any]] = {"added": {}, "removed": {}, "modified": {}}

    # Same value - no difference
    if old == new:
        return False if early_exit else diff

    # Different types
    if type(old) != type(new):
        if early_exit:
            return True
        diff["modified"][path if path else "<root>"] = {"old": old, "new": new}
        return diff

    # Both are dicts
    if isinstance(old, dict) and isinstance(new, dict):
        old_keys = set(old.keys())
        new_keys = set(new.keys())

        # Added keys
        for k in new_keys - old_keys:
            p = f"{path}.{k}" if path else k
            if early_exit:
                return True
            diff["added"][p] = {"old": None, "new": new[k]}

        # Removed keys
        for k in old_keys - new_keys:
            p = f"{path}.{k}" if path else k
            if early_exit:
                return True
            diff["removed"][p] = {"old": old[k], "new": None}

        # Common keys - recurse
        for k in old_keys & new_keys:
            p = f"{path}.{k}" if path else k
            sub_result = compute_diff(old[k], new[k], p, early_exit)

            if early_exit:
                if sub_result:  # True means difference found
                    return True
            else:
                # Merge sub-diffs (sub_result is a dict when early_exit=False)
                sub_diff = cast(Dict[str, Dict[str, Any]], sub_result)
                for t in ("added", "removed", "modified"):
                    diff[t].update(sub_diff[t])

        return False if early_exit else diff

    # Both are lists
    if isinstance(old, list) and isinstance(new, list):
        max_len = max(len(old), len(new))

        for i in range(max_len):
            p = f"{path}[{i}]" if path else f"[{i}]"

            if i >= len(old):
                # Added item
                if early_exit:
                    return True
                diff["added"][p] = {"old": None, "new": new[i]}
            elif i >= len(new):
                # Removed item
                if early_exit:
                    return True
                diff["removed"][p] = {"old": old[i], "new": None}
            else:
                # Both exist - recurse
                sub_result = compute_diff(old[i], new[i], p, early_exit)

                if early_exit:
                    if sub_result:  # True means difference found
                        return True
                else:
                    # Merge sub-diffs (sub_result is a dict when early_exit=False)
                    sub_diff = cast(Dict[str, Dict[str, Any]], sub_result)
                    for t in ("added", "removed", "modified"):
                        diff[t].update(sub_diff[t])

        return False if early_exit else diff

    # Primitives that are different (we already checked old == new above)
    if early_exit:
        return True
    diff["modified"][path if path else "<root>"] = {"old": old, "new": new}
    return diff


def deep_equals(a: Any, b: Any) -> bool:
    """Perform deep equality comparison of two values.

    Handles nested dicts, lists, and primitive types. Uses compute_diff
    with early_exit=True for efficient short-circuit evaluation.

    Args:
        a: First value to compare
        b: Second value to compare

    Returns:
        True if values are deeply equal, False otherwise
    """
    # compute_diff returns False when no differences found (early_exit mode)
    return compute_diff(a, b, early_exit=True) is False


def has_diff(diff: Dict[str, Any]) -> bool:
    """Check if a diff result contains any changes.

    Args:
        diff: The diff dict returned by compute_diff(early_exit=False)

    Returns:
        True if any changes exist, False otherwise
    """
    return any(diff.values())
