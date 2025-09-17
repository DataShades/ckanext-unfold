import os

import pytest

import ckanext.unfold.truncate as unf_truncate
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils


@pytest.mark.parametrize(
    "max_depth,expected_truncated,expected_max_depth",
    [
        (None, False, 5),  # No limit - files go to depth 5
        (10, False, 5),  # High limit - no truncation
        (3, True, 3),  # Should truncate at depth 4+
        (2, True, 2),  # Should truncate at depth 3+
        (1, True, 1),  # Should truncate at depth 2+
    ],
)
def test_build_tree_with_depth_limits(
    max_depth, expected_truncated, expected_max_depth
):
    file_path = os.path.join(os.path.dirname(__file__), "data/test_complex_nested.zip")
    tree = unf_utils.get_adapter_for_format("zip")(file_path, {})
    truncated_tree = unf_truncate.apply_all_truncations(tree, max_depth=max_depth)

    # Check for truncation indicators
    truncation_nodes = [n for n in truncated_tree if n.id.endswith("__truncated__")]
    has_truncation = len(truncation_nodes) > 0
    assert has_truncation == expected_truncated

    # Verify actual max depth in result
    actual_max_depth = 0
    for node in truncated_tree:
        if not node.id.endswith("__truncated__"):
            depth = len([p for p in node.id.split("/") if p]) - 1
            actual_max_depth = max(actual_max_depth, depth)
    assert actual_max_depth <= expected_max_depth

    assert type(truncated_tree[0]) == unf_types.Node


@pytest.mark.parametrize(
    "max_nested_count,expected_truncated,expected_truncation_count",
    [
        (None, False, 0),  # No limit
        (
            15,
            False,
            0,
        ),  # High limit - each folder has 10 files + 4 subfolders = 14 items
        (
            8,
            True,
            20,
        ),  # Should truncate - each of 4 main folders + 16 level_1 folders get truncated
        (5, True, 20),  # More truncation
        (2, True, 20),  # Even more truncation
    ],
)
def test_build_tree_with_nested_count_limits(
    max_nested_count, expected_truncated, expected_truncation_count
):
    file_path = os.path.join(os.path.dirname(__file__), "data/test_complex_nested.zip")
    tree = unf_utils.get_adapter_for_format("zip")(file_path, {})
    truncated_tree = unf_truncate.apply_all_truncations(
        tree, max_nested_count=max_nested_count
    )

    # Check for truncation indicators
    truncation_nodes = [n for n in truncated_tree if n.id.endswith("__truncated__")]
    has_truncation = len(truncation_nodes) > 0
    assert has_truncation == expected_truncated

    # For cases with truncation, check approximate count (allow some variance)
    if expected_truncated:
        assert (
            len(truncation_nodes) >= expected_truncation_count * 0.5
        )  # Allow some variance

    assert type(truncated_tree[0]) == unf_types.Node


@pytest.mark.parametrize(
    "max_count,expected_truncated",
    [
        (None, False),  # No limit
        (15006, False),  # Above total count (13640 + 1365 = 15005)
        (10000, True),  # Below total count - should truncate
        (1000, True),  # Much smaller - should truncate heavily
        (100, True),  # Very small - major truncation
        (10, True),  # Tiny limit
    ],
)
def test_build_tree_with_total_count_limits(max_count, expected_truncated):
    file_path = os.path.join(os.path.dirname(__file__), "data/test_complex_nested.zip")
    tree = unf_utils.get_adapter_for_format("zip")(file_path, {})
    truncated_tree = unf_truncate.apply_all_truncations(tree, max_count=max_count)

    # Check total count limit is respected
    if max_count:
        assert len(truncated_tree) <= max_count

    truncation_nodes = [n for n in truncated_tree if n.id.endswith("__truncated__")]
    has_truncation = len(truncation_nodes) > 0
    assert has_truncation == expected_truncated

    assert type(truncated_tree[0]) == unf_types.Node
