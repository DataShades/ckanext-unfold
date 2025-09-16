import pathlib

import pytest

import ckanext.unfold.types as unf_types


@pytest.fixture
def create_test_node():
    def _create_test_node(node_id: str, node_type: str = None) -> unf_types.Node:
        path = pathlib.Path(node_id)
        parent = (
            path.parent.as_posix() if path.parent.as_posix() not in ["/", "."] else "#"
        )
        if node_type is None:
            node_type = "file" if path.suffix else "folder"
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
                "modified_at": "01/01/2024 - 12:00",
            },
        )

    return _create_test_node


@pytest.fixture
def complex_tree(create_test_node):
    nodes = [
        create_test_node("a"),
        create_test_node("a/file1.txt"),
        create_test_node("a/file2.config.json"),
        create_test_node("a/file3.yml"),
        create_test_node("a/file4.py"),
        create_test_node("a/file5.R"),
        create_test_node("a/file6.pdf"),
        create_test_node("a/file7", "file"),
        create_test_node("a/b"),
        create_test_node("a/b/file1", "file"),
        create_test_node("a/b/file2", "file"),
        create_test_node("a/b/file3", "file"),
        create_test_node("a/b/file4", "file"),
        create_test_node("a/b/file5", "file"),
        create_test_node("a/b/file6", "file"),
        create_test_node("a/b/file7", "file"),
        create_test_node("a/b/file8", "file"),
        create_test_node("a/b/c"),
        create_test_node("a/b/c/file1.md"),
        create_test_node("a/b/c/file2.pdf"),
        create_test_node("a/b/c/d"),
        create_test_node("a/b/c/d/file1", "file"),
        create_test_node("a/b/c/d/file2", "file"),
        create_test_node("a/b/c/d/file3", "file"),
        create_test_node("a/b/c/d/file4", "file"),
        create_test_node("a/b/c/d/file5", "file"),
        create_test_node("a/b/c/d/file6", "file"),
        create_test_node("a/b/c/d/file7", "file"),
        create_test_node("a/b/c/d/file8", "file"),
        create_test_node("a/x"),
        create_test_node("a/x/file1.tar.gz"),
        create_test_node("a/x/file2.tz"),
        create_test_node("a/x/file3.rar"),
        create_test_node("a/x/file3.zip"),
        create_test_node("a/x/y"),
        create_test_node("a/x/y/file1", "file"),
        create_test_node("a/x/y/file2", "file"),
        create_test_node("a/x/y/file3", "file"),
        create_test_node("a/x/y/file4", "file"),
        create_test_node("a/x/y/file5", "file"),
        create_test_node("a/x/y/z"),
        create_test_node("a/x/y/z/file1", "file"),
        create_test_node("a/x/y/z/file2", "file"),
        create_test_node("a/x/y/z/file3", "file"),
        create_test_node("a/x/y/z/file4", "file"),
    ]
    return nodes
