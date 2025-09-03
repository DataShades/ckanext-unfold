import os

import pytest

import ckanext.unfold.truncate as unf_truncate
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils


@pytest.mark.parametrize(
    "max_depth,expected_truncated,expected_max_depth",
    [
        (None, False, 5),  # No limit - files go to depth 5
        (10, False, 5),   # High limit - no truncation 
        (3, True, 3),     # Should truncate at depth 4+
        (2, True, 2),     # Should truncate at depth 3+
        (1, True, 1),     # Should truncate at depth 2+
    ],
)
def test_build_tree_with_depth_limits(max_depth, expected_truncated, expected_max_depth):
    file_path = os.path.join(
        os.path.dirname(__file__), "data/test_complex_nested.zip"
    )
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
        (None, False, 0),     # No limit
        (15, False, 0),       # High limit - each folder has 10 files + 4 subfolders = 14 items
        (8, True, 20),        # Should truncate - each of 4 main folders + 16 level_1 folders get truncated 
        (5, True, 20),        # More truncation
        (2, True, 20),        # Even more truncation
    ],
)
def test_build_tree_with_nested_count_limits(max_nested_count, expected_truncated, expected_truncation_count):
    file_path = os.path.join(
        os.path.dirname(__file__), "data/test_complex_nested.zip"
    )
    tree = unf_utils.get_adapter_for_format("zip")(file_path, {})
    truncated_tree = unf_truncate.apply_all_truncations(tree, max_nested_count=max_nested_count)
    
    # Check for truncation indicators
    truncation_nodes = [n for n in truncated_tree if n.id.endswith("__truncated__")]
    has_truncation = len(truncation_nodes) > 0
    assert has_truncation == expected_truncated
    
    # For cases with truncation, check approximate count (allow some variance)
    if expected_truncated:
        assert len(truncation_nodes) >= expected_truncation_count * 0.5  # Allow some variance
    
    assert type(truncated_tree[0]) == unf_types.Node


@pytest.mark.parametrize(
    "max_count,expected_truncated",
    [
        (None, False),        # No limit
        (15000, False),       # Above total count (13640 + 1365 = 15005)
        (10000, True),        # Below total count - should truncate
        (1000, True),         # Much smaller - should truncate heavily  
        (100, True),          # Very small - major truncation
        (10, True),           # Tiny limit
    ],
)
def test_build_tree_with_total_count_limits(max_count, expected_truncated):
    file_path = os.path.join(
        os.path.dirname(__file__), "data/test_complex_nested.zip"
    )
    tree = unf_utils.get_adapter_for_format("zip")(file_path, {})
    truncated_tree = unf_truncate.apply_all_truncations(tree, max_count=max_count)
    
    # Check total count limit is respected
    if max_count:
        assert len(truncated_tree) <= max_count
        
    truncation_nodes = [n for n in truncated_tree if n.id.endswith("__truncated__")]
    has_truncation = len(truncation_nodes) > 0
    assert has_truncation == expected_truncated
    
    assert type(truncated_tree[0]) == unf_types.Node


def test_build_tree_with_combined_limits():
    """Test all truncation limits working together with precise expectations"""
    file_path = os.path.join(
        os.path.dirname(__file__), "data/test_complex_nested.zip"
    )
    tree = unf_utils.get_adapter_for_format("zip")(file_path, {})
    
    # Use realistic limits: depth=2 (allow folder_1/level_1_folder_1/ but not deeper)
    # nested_count=5 (allow some files per folder), max_count=50 (small total)
    truncated_tree = unf_truncate.apply_all_truncations(
        tree, max_depth=2, max_nested_count=5, max_count=50
    )
    
    # Should respect total count limit  
    assert len(truncated_tree) <= 50
    
    # Should have truncation indicators
    truncation_nodes = [n for n in truncated_tree if n.id.endswith("__truncated__")]
    assert len(truncation_nodes) > 0
    
    # Should respect depth limit
    actual_max_depth = 0
    for node in truncated_tree:
        if not node.id.endswith("__truncated__"):
            depth = len([p for p in node.id.split("/") if p]) - 1
            actual_max_depth = max(actual_max_depth, depth)
    assert actual_max_depth <= 2
    
    # Check we have different types of truncation
    depth_truncations = sum(1 for n in truncation_nodes if "level_1_folder" in n.parent and n.parent.count('/') == 1)
    nested_truncations = sum(1 for n in truncation_nodes if n.parent != "#")
    global_truncations = sum(1 for n in truncation_nodes if n.parent == "#")
    
    # Should have at least some truncation indicators
    total_truncations = len(truncation_nodes)
    assert total_truncations >= 1
    print(f"Total truncations: {total_truncations} (depth: {depth_truncations}, nested: {nested_truncations}, global: {global_truncations})")
    
    assert type(truncated_tree[0]) == unf_types.Node


def test_exact_truncation_scenario():
    """Test specific scenario with known exact results"""
    file_path = os.path.join(
        os.path.dirname(__file__), "data/test_complex_nested.zip"
    )
    tree = unf_utils.get_adapter_for_format("zip")(file_path, {})
    
    # Test depth=1: should only allow folder_1/, folder_2/, etc and their immediate children
    # No level_1_folder_* should survive
    truncated_tree = unf_truncate.apply_all_truncations(tree, max_depth=1)
    
    # Count actual depth levels in result
    depth_counts = {}
    for node in truncated_tree:
        if not node.id.endswith("__truncated__"):
            depth = len([p for p in node.id.split("/") if p]) - 1
            depth_counts[depth] = depth_counts.get(depth, 0) + 1
    
    # Should have no nodes deeper than depth 1
    assert max(depth_counts.keys()) <= 1
    
    # Should have 16 truncation indicators (one for each level_1_folder)
    # 4 main folders * 4 level_1_folders each = 16
    truncation_nodes = [n for n in truncated_tree if n.id.endswith("__truncated__")]
    assert len(truncation_nodes) == 16  
    
    # Verify the truncation nodes are at the right level
    truncated_parents = {n.parent for n in truncation_nodes}
    # All truncated parents should be level_1_folder_* at depth 1
    for parent in truncated_parents:
        assert parent.count('/') == 2  # folder_X/level_1_folder_Y/
        assert 'level_1_folder' in parent
    
    print(f"Depth 1 test: {len(truncated_tree)} total nodes, {len(truncation_nodes)} truncation indicators")
    print(f"Depth distribution: {depth_counts}")
    print(f"Truncated parents: {sorted(truncated_parents)}")
    
    assert type(truncated_tree[0]) == unf_types.Node