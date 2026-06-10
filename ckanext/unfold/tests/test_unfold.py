import os
from types import SimpleNamespace

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


def test_prepare_ckanext_files_resource(monkeypatch):
    file_info = {
        "id": "file-id",
        "name": "archive.zip",
        "location": "archives/archive.zip",
        "storage": "resources",
        "size": 100,
        "content_type": "application/zip",
    }

    class Storage:
        def temporary_link(self, data, duration):
            assert data.location == "archives/archive.zip"
            assert duration == utils.TEMPORARY_LINK_TTL
            return "https://storage.example/archive.zip?signature=test"

    monkeypatch.setattr(
        utils.tk,
        "get_action",
        lambda _name: lambda _context, _data: file_info,
    )
    files_api = SimpleNamespace(
        get_storage=lambda _name: Storage(),
        FileData=SimpleNamespace(
            from_dict=lambda data: SimpleNamespace(location=data["location"])
        ),
    )
    monkeypatch.setattr(utils, "_get_files_api", lambda: files_api)

    resource = {
        "url": "https://ckan.example/file/download/file-id",
        "url_type": "file",
        "size": None,
    }
    with utils._prepare_file_resource(resource, {}) as (prepared, filepath):
        assert prepared["type"] == "url"
        assert prepared["url"].startswith("https://storage.example/")
        assert prepared["size"] == 100
        assert filepath is None
