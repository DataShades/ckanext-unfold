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
    tree = utils.get_adapter_for_format(file_format)(file_path, {})

    assert len(tree) == num_nodes
    assert isinstance(tree[0], types.Node)
