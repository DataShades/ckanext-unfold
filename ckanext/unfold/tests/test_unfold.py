import os

import pytest

from ckanext.unfold import types, utils


@pytest.mark.usefixtures("with_request_context")
@pytest.mark.parametrize(
    ("file_format", "num_nodes"),
    [
        ("rar", 13),
        ("cbr", 38),
        ("7z", 5),
        ("zip", 11),
        ("zipx", 4),
        ("jar", 76),
        ("tar", 5),
        ("tar.gz", 1),
        ("tar.xz", 1),
        ("tar.bz2", 1),
        ("rpm", 355),
        ("deb", 3),
        ("ar", 1),
        ("a", 2),
        ("lib", 2),
    ],
)
def test_build_tree(file_format: str, num_nodes: int):
    file_path = os.path.join(
        os.path.dirname(__file__), f"data/test_archive.{file_format}"
    )
    adapter_instance = utils.get_adapter_for_resource({"format": file_format})(
        file_path, {}, {}, remote=False
    )
    tree = adapter_instance.build_archive_tree()

    assert len(tree) == num_nodes
    assert isinstance(tree[0], types.Node)


def test_build_complex_tree():
    adapter_instance = utils.get_adapter_for_resource({"format": "zip"})(
        os.path.join(os.path.dirname(__file__), "data/test_complex_nested.zip"),
        {},
        {},
        remote=False,
    )
    tree = adapter_instance.build_archive_tree()

    assert len(tree) == 15004
    root_folders = [node for node in tree if node.parent == "#"]
    assert len(root_folders) == 4
