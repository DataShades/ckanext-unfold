from __future__ import annotations

import pytest

import ckanext.unfold.truncate as unf_truncate
import ckanext.unfold.types as unf_types


@pytest.fixture
def create_test_node():
    def _create_test_node(node_id: str, parent: str = "#", node_type: str = "file") -> unf_types.Node:
        icon = "fa fa-folder" if node_type == "folder" else "fa fa-file"
        return unf_types.Node(
            id=node_id,
            text=node_id.split("/")[-1],
            icon=icon,
            parent=parent,
            state={"opened": True},
            data={
                "size": "1024",
                "type": node_type,
                "format": "txt" if node_type == "file" else "",
                "modified_at": "01/01/2024 - 12:00"
            }
        )
    return _create_test_node


@pytest.fixture
def simple_tree(create_test_node):
    return [
        create_test_node("root", "#", "folder"),
        create_test_node("root/file1.txt", "root", "file"),
        create_test_node("root/file2.txt", "root", "file"),
        create_test_node("root/subfolder", "root", "folder"),
        create_test_node("root/subfolder/file3.txt", "root/subfolder", "file"),
        create_test_node("root/subfolder/file4.txt", "root/subfolder", "file"),
    ]


@pytest.fixture
def deep_tree(create_test_node):
    return [
        create_test_node("root", "#", "folder"),
        create_test_node("root/level1", "root", "folder"),
        create_test_node("root/level1/level2", "root/level1", "folder"),
        create_test_node("root/level1/level2/level3", "root/level1/level2", "folder"),
        create_test_node("root/level1/level2/level3/file.txt", "root/level1/level2/level3", "file"),
    ]


@pytest.fixture
def wide_tree(create_test_node):
    nodes = [create_test_node("root", "#", "folder")]
    for i in range(10):
        nodes.append(create_test_node(f"root/file{i}.txt", "root", "file"))
    return nodes


@pytest.mark.parametrize("parent_id,count,node_type,expected_icon", [
    ("parent", 5, "folder", "fa fa-folder"),
    ("parent", 3, "file", "fa fa-file"),
])
def test_create_truncation_node(parent_id, count, node_type, expected_icon):
    node = unf_truncate.create_truncation_node(parent_id, count, node_type)
    
    assert node.id == f"{parent_id}/__truncated__"
    assert node.text == f"... ({count} more items truncated)"
    assert node.icon == expected_icon
    assert node.parent == parent_id
    assert node.data["type"] == "truncation"


@pytest.mark.parametrize("archive_size,max_size,expected", [
    (1000, 2000, True),
    (2000, 1000, False),
    (1000, None, True),
    (None, 1000, True),
])
def test_check_size_limit(archive_size, max_size, expected):
    result = unf_truncate.check_size_limit(archive_size, max_size)
    assert result == expected


@pytest.mark.parametrize("nodes,max_depth,max_nested_count,max_count", [
    ([], None, None, None),
    ("simple_tree", None, None, None),
    ("simple_tree", -1, -1, -1),
])
def test_apply_all_truncations_no_limits(nodes, max_depth, max_nested_count, max_count, simple_tree):
    if nodes == "simple_tree":
        nodes = simple_tree
    result = unf_truncate.apply_all_truncations(nodes, max_depth, max_nested_count, max_count)
    assert len(result) == len(nodes)


def test_depth_truncation_at_level_1(deep_tree):
    result = unf_truncate.apply_all_truncations(deep_tree, max_depth=1)
    
    kept_ids = {node.id for node in result if not node.id.endswith("__truncated__")}
    assert "root" in kept_ids
    assert "root/level1" in kept_ids
    assert "root/level1/level2" not in kept_ids
    
    truncation_nodes = [node for node in result if node.id.endswith("__truncated__")]
    assert len(truncation_nodes) == 1
    assert truncation_nodes[0].parent == "root/level1"


def test_nested_count_truncation_limit_2(wide_tree):
    result = unf_truncate.apply_all_truncations(wide_tree, max_nested_count=2)
    
    kept_files = [node for node in result if not node.id.endswith("__truncated__")]
    assert len(kept_files) == 3  # root + 2 files
    
    truncation_nodes = [node for node in result if node.id.endswith("__truncated__")]
    assert len(truncation_nodes) == 1
    assert truncation_nodes[0].parent == "root"


def test_total_count_truncation_limit_3(simple_tree):
    result = unf_truncate.apply_all_truncations(simple_tree, max_count=3)
    
    assert len(result) == 3
    
    truncation_nodes = [node for node in result if node.id.endswith("__truncated__")]
    assert len(truncation_nodes) == 1
    assert truncation_nodes[0].parent == "#"


def test_truncation_indicators_have_correct_data(deep_tree, wide_tree, simple_tree):
    depth_result = unf_truncate.apply_all_truncations(deep_tree, max_depth=1)
    nested_result = unf_truncate.apply_all_truncations(wide_tree, max_nested_count=3)
    count_result = unf_truncate.apply_all_truncations(simple_tree, max_count=2)
    
    for result in [depth_result, nested_result, count_result]:
        truncation_nodes = [node for node in result if node.id.endswith("__truncated__")]
        assert len(truncation_nodes) == 1
        
        indicator = truncation_nodes[0]
        assert indicator.data["type"] == "truncation"
        assert "more items truncated" in indicator.text
        assert indicator.state == {"opened": False}


def test_no_duplicate_truncation_indicators(create_test_node):
    nodes = [create_test_node("root", "#", "folder")]
    for i in range(5):
        nodes.append(create_test_node(f"root/file{i}.txt", "root", "file"))
    
    result = unf_truncate.apply_all_truncations(nodes, max_nested_count=2)
    
    truncation_nodes = [node for node in result if node.id.endswith("__truncated__")]
    assert len(truncation_nodes) == 1
    assert truncation_nodes[0].parent == "root"


def test_combined_truncation_limits(create_test_node):
    nodes = [create_test_node("root", "#", "folder")]
    for i in range(20):
        nodes.append(create_test_node(f"root/file{i}.txt", "root", "file"))
    
    result = unf_truncate.apply_all_truncations(
        nodes, 
        max_depth=1, 
        max_nested_count=5, 
        max_count=8
    )
    
    assert len(result) <= 8
    
    truncation_nodes = [node for node in result if node.id.endswith("__truncated__")]
    assert len(truncation_nodes) >= 1