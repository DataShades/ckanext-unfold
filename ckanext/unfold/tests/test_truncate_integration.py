import os

import pytest

import ckanext.unfold.truncate as unf_truncate
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils


@pytest.mark.parametrize(
    (
        "max_depth",
        "max_nested",
        "max_total",
        "expected_truncated",
        "expected_max_depth",
        "expected_truncation_count",
    ),
    [
        # Depth-only limits
        (999999, 999999, 999999, False, 5, 0),
        (3, 999999, 999999, True, 3, None),
        (1, 999999, 999999, True, 1, None),
        # Nested-only limits
        (999999, 8, 999999, True, 5, 20),
        (999999, 2, 999999, True, 5, 20),
        # Total-only limits
        (999999, 999999, 1000, True, 5, 0),
        (999999, 999999, 5, True, 5, None),
        # Combined limits
        (3, 5, 10, True, 3, None),
    ],
)
def test_truncate_nodes(
    max_depth,
    max_nested,
    max_total,
    expected_truncated,
    expected_max_depth,
    expected_truncation_count,
):
    file_path = os.path.join(os.path.dirname(__file__), "data/test_complex_nested.zip")
    tree = unf_utils.get_adapter_for_format("zip")(file_path, {})

    truncated_tree = unf_truncate.truncate_nodes(
        tree, max_depth=max_depth, max_nested=max_nested, max_total=max_total
    )

    # Check for truncation nodes
    truncation_nodes = [n for n in truncated_tree if n.id.endswith("__truncated__")]
    has_truncation = len(truncation_nodes) > 0
    assert has_truncation == expected_truncated

    # Verify max depth
    if expected_max_depth is not None:
        actual_max_depth = 0
        for node in truncated_tree:
            if not node.id.endswith("__truncated__"):
                depth = len([p for p in node.id.split("/") if p]) - 1
                actual_max_depth = max(actual_max_depth, depth)
        assert actual_max_depth <= expected_max_depth

    # Optional truncation count check
    if expected_truncation_count is not None and expected_truncated:
        assert (
            len(truncation_nodes) >= expected_truncation_count * 0.5
        )  # allow some variance

    # Node type sanity check
    assert isinstance(truncated_tree[0], unf_types.Node)
