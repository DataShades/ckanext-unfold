import os
from contextlib import contextmanager
from typing import Iterator

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

    adapter = utils.get_adapter_for_resource({"format": file_format})
    adapter_instance = adapter({}, {}, filepath=file_path)
    tree = adapter_instance.build_archive_tree()

    assert len(tree) == num_nodes
    assert isinstance(tree[0], types.Node)


def test_build_complex_tree():
    file_path = os.path.join(os.path.dirname(__file__), "data/test_complex_nested.zip")
    adapter = utils.get_adapter_for_resource({"format": "zip"})
    adapter_instance = adapter({}, {}, filepath=file_path)
    tree = adapter_instance.build_archive_tree()

    assert len(tree) == 15004
    root_folders = [node for node in tree if node.parent == "#"]
    assert len(root_folders) == 4


@pytest.mark.usefixtures("with_request_context")
def test_build_file_resource_tree(monkeypatch, ckan_config):
    file_path = os.path.join(os.path.dirname(__file__), "data/test_archive.zip")
    resource = {
        "id": "file-resource",
        "format": "zip",
        "url_type": "file",
    }
    ckan_config["ckanext.unfold.enable_cache"] = False

    @contextmanager
    def prepare_file_resource(
        resource: dict,
        context: dict,
    ) -> Iterator[tuple[dict, str]]:
        yield resource, file_path

    monkeypatch.setattr(utils, "_prepare_file_resource", prepare_file_resource)

    tree = utils.get_archive_tree(resource, {})

    assert len(tree) == 11
    assert isinstance(tree[0], types.Node)
