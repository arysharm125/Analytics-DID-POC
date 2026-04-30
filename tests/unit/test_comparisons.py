"""Unit tests for app/did_utils/comparisons.py deep comparison functions."""

from app.did_utils.comparisons import compute_diff, deep_equals, has_diff


class TestDeepEquals:
    """Tests for deep_equals function."""

    def test_equal_primitives(self):
        """Equal primitives should return True."""
        assert deep_equals(1, 1) is True
        assert deep_equals("hello", "hello") is True
        assert deep_equals(True, True) is True
        assert deep_equals(None, None) is True
        assert deep_equals(3.14, 3.14) is True

    def test_unequal_primitives(self):
        """Unequal primitives should return False."""
        assert deep_equals(1, 2) is False
        assert deep_equals("hello", "world") is False
        assert deep_equals(True, False) is False
        assert deep_equals(None, 0) is False
        assert deep_equals(1, "1") is False

    def test_equal_empty_dicts(self):
        """Empty dicts should be equal."""
        assert deep_equals({}, {}) is True

    def test_equal_simple_dicts(self):
        """Simple dicts with same content should be equal."""
        assert deep_equals({"a": 1, "b": 2}, {"a": 1, "b": 2}) is True

    def test_unequal_dicts_different_values(self):
        """Dicts with different values should be unequal."""
        assert deep_equals({"a": 1}, {"a": 2}) is False

    def test_unequal_dicts_different_keys(self):
        """Dicts with different keys should be unequal."""
        assert deep_equals({"a": 1}, {"b": 1}) is False

    def test_unequal_dicts_extra_key(self):
        """Dict with extra key should be unequal."""
        assert deep_equals({"a": 1}, {"a": 1, "b": 2}) is False

    def test_unequal_dicts_missing_key(self):
        """Dict with missing key should be unequal."""
        assert deep_equals({"a": 1, "b": 2}, {"a": 1}) is False

    def test_equal_nested_dicts(self):
        """Nested dicts with same content should be equal."""
        d1 = {"a": {"b": {"c": 1}}}
        d2 = {"a": {"b": {"c": 1}}}
        assert deep_equals(d1, d2) is True

    def test_unequal_nested_dicts(self):
        """Nested dicts with different content should be unequal."""
        d1 = {"a": {"b": {"c": 1}}}
        d2 = {"a": {"b": {"c": 2}}}
        assert deep_equals(d1, d2) is False

    def test_equal_empty_lists(self):
        """Empty lists should be equal."""
        assert deep_equals([], []) is True

    def test_equal_simple_lists(self):
        """Simple lists with same content should be equal."""
        assert deep_equals([1, 2, 3], [1, 2, 3]) is True

    def test_unequal_lists_different_values(self):
        """Lists with different values should be unequal."""
        assert deep_equals([1, 2, 3], [1, 2, 4]) is False

    def test_unequal_lists_different_lengths(self):
        """Lists with different lengths should be unequal."""
        assert deep_equals([1, 2, 3], [1, 2]) is False
        assert deep_equals([1, 2], [1, 2, 3]) is False

    def test_equal_nested_lists(self):
        """Nested lists with same content should be equal."""
        l1 = [[1, 2], [3, 4]]
        l2 = [[1, 2], [3, 4]]
        assert deep_equals(l1, l2) is True

    def test_unequal_nested_lists(self):
        """Nested lists with different content should be unequal."""
        l1 = [[1, 2], [3, 4]]
        l2 = [[1, 2], [3, 5]]
        assert deep_equals(l1, l2) is False

    def test_equal_mixed_structures(self):
        """Mixed structures with same content should be equal."""
        s1 = {"items": [1, 2, {"nested": True}], "count": 3}
        s2 = {"items": [1, 2, {"nested": True}], "count": 3}
        assert deep_equals(s1, s2) is True

    def test_unequal_mixed_structures(self):
        """Mixed structures with different content should be unequal."""
        s1 = {"items": [1, 2, {"nested": True}], "count": 3}
        s2 = {"items": [1, 2, {"nested": False}], "count": 3}
        assert deep_equals(s1, s2) is False

    def test_different_types(self):
        """Different types should be unequal."""
        assert deep_equals({}, []) is False
        assert deep_equals([], "") is False
        assert deep_equals({"a": 1}, [("a", 1)]) is False


class TestComputeDiff:
    """Tests for compute_diff function."""

    def test_identical_primitives(self):
        """Identical primitives should have no diff."""
        diff = compute_diff(1, 1)
        assert diff == {"added": {}, "removed": {}, "modified": {}}

    def test_modified_primitives(self):
        """Different primitives should show modification."""
        diff = compute_diff(1, 2)
        assert diff["modified"] == {"<root>": {"old": 1, "new": 2}}
        assert diff["added"] == {}
        assert diff["removed"] == {}

    def test_different_types(self):
        """Different types should show modification."""
        diff = compute_diff("hello", 123)
        assert diff["modified"] == {"<root>": {"old": "hello", "new": 123}}

    def test_added_key(self):
        """New key should show as added."""
        diff = compute_diff({"a": 1}, {"a": 1, "b": 2})
        assert diff["added"] == {"b": {"old": None, "new": 2}}
        assert diff["removed"] == {}
        assert diff["modified"] == {}

    def test_removed_key(self):
        """Missing key should show as removed."""
        diff = compute_diff({"a": 1, "b": 2}, {"a": 1})
        assert diff["removed"] == {"b": {"old": 2, "new": None}}
        assert diff["added"] == {}
        assert diff["modified"] == {}

    def test_modified_key(self):
        """Changed value should show as modified."""
        diff = compute_diff({"a": 1}, {"a": 2})
        assert diff["modified"] == {"a": {"old": 1, "new": 2}}
        assert diff["added"] == {}
        assert diff["removed"] == {}

    def test_nested_dict_change(self):
        """Nested change should include full path."""
        diff = compute_diff(
            {"outer": {"inner": 1}},
            {"outer": {"inner": 2}}
        )
        assert diff["modified"] == {"outer.inner": {"old": 1, "new": 2}}

    def test_deeply_nested_change(self):
        """Deeply nested change should include full path."""
        diff = compute_diff(
            {"a": {"b": {"c": {"d": 1}}}},
            {"a": {"b": {"c": {"d": 2}}}}
        )
        assert diff["modified"] == {"a.b.c.d": {"old": 1, "new": 2}}

    def test_list_item_added(self):
        """Added list item should show as added."""
        diff = compute_diff([1, 2], [1, 2, 3])
        assert diff["added"] == {"[2]": {"old": None, "new": 3}}

    def test_list_item_removed(self):
        """Removed list item should show as removed."""
        diff = compute_diff([1, 2, 3], [1, 2])
        assert diff["removed"] == {"[2]": {"old": 3, "new": None}}

    def test_list_item_modified(self):
        """Changed list item should show as modified."""
        diff = compute_diff([1, 2, 3], [1, 5, 3])
        assert diff["modified"] == {"[1]": {"old": 2, "new": 5}}

    def test_nested_list_change(self):
        """Nested list change should include full path."""
        diff = compute_diff(
            {"items": [1, 2, 3]},
            {"items": [1, 2, 4]}
        )
        assert diff["modified"] == {"items[2]": {"old": 3, "new": 4}}

    def test_list_with_dict_change(self):
        """Dict inside list change should include full path."""
        diff = compute_diff(
            {"items": [{"name": "foo"}]},
            {"items": [{"name": "bar"}]}
        )
        assert diff["modified"] == {"items[0].name": {"old": "foo", "new": "bar"}}

    def test_multiple_changes(self):
        """Multiple changes should all be captured."""
        diff = compute_diff(
            {"a": 1, "b": 2, "c": 3},
            {"a": 1, "b": 5, "d": 4}
        )
        assert diff["added"] == {"d": {"old": None, "new": 4}}
        assert diff["removed"] == {"c": {"old": 3, "new": None}}
        assert diff["modified"] == {"b": {"old": 2, "new": 5}}

    def test_empty_dicts_no_diff(self):
        """Empty dicts should have no diff."""
        diff = compute_diff({}, {})
        assert diff == {"added": {}, "removed": {}, "modified": {}}

    def test_empty_lists_no_diff(self):
        """Empty lists should have no diff."""
        diff = compute_diff([], [])
        assert diff == {"added": {}, "removed": {}, "modified": {}}


class TestComputeDiffEarlyExit:
    """Tests for compute_diff with early_exit=True."""

    def test_identical_returns_false(self):
        """Identical values should return False."""
        assert compute_diff({"a": 1}, {"a": 1}, early_exit=True) is False

    def test_different_returns_true(self):
        """Different values should return True."""
        assert compute_diff({"a": 1}, {"a": 2}, early_exit=True) is True

    def test_added_key_returns_true(self):
        """Added key should return True."""
        assert compute_diff({"a": 1}, {"a": 1, "b": 2}, early_exit=True) is True

    def test_removed_key_returns_true(self):
        """Removed key should return True."""
        assert compute_diff({"a": 1, "b": 2}, {"a": 1}, early_exit=True) is True

    def test_nested_difference_returns_true(self):
        """Nested difference should return True."""
        assert compute_diff(
            {"a": {"b": 1}},
            {"a": {"b": 2}},
            early_exit=True
        ) is True

    def test_list_difference_returns_true(self):
        """List difference should return True."""
        assert compute_diff([1, 2], [1, 3], early_exit=True) is True


class TestHasDiff:
    """Tests for has_diff function."""

    def test_empty_diff_returns_false(self):
        """Empty diff should return False."""
        diff = {"added": {}, "removed": {}, "modified": {}}
        assert has_diff(diff) is False

    def test_added_diff_returns_true(self):
        """Diff with additions should return True."""
        diff = {"added": {"key": {"old": None, "new": 1}}, "removed": {}, "modified": {}}
        assert has_diff(diff) is True

    def test_removed_diff_returns_true(self):
        """Diff with removals should return True."""
        diff = {"added": {}, "removed": {"key": {"old": 1, "new": None}}, "modified": {}}
        assert has_diff(diff) is True

    def test_modified_diff_returns_true(self):
        """Diff with modifications should return True."""
        diff = {"added": {}, "removed": {}, "modified": {"key": {"old": 1, "new": 2}}}
        assert has_diff(diff) is True

    def test_multiple_changes_returns_true(self):
        """Diff with multiple changes should return True."""
        diff = {
            "added": {"a": {"old": None, "new": 1}},
            "removed": {"b": {"old": 2, "new": None}},
            "modified": {"c": {"old": 3, "new": 4}}
        }
        assert has_diff(diff) is True
