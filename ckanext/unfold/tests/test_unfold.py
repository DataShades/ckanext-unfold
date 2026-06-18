import os
import re

import pytest

from ckanext.unfold import types, utils

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BASE_URL = "http://archives.test/"


def _range_response(data: bytes):
    """Build a requests_mock callback that serves ``data`` with Range support.

    Honors ``bytes=a-b``, ``bytes=a-`` and suffix ``bytes=-n`` requests so the
    ZIP tail fast-path (206 + Content-Range) is exercised; a request without a
    Range falls back to a full 200 response.
    """
    size = len(data)

    def _callback(request, context):
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", request.headers.get("Range", ""))

        if not match or match.group(1) == match.group(2) == "":
            context.status_code = 200
            context.headers["Content-Length"] = str(size)
            return data

        first, last = match.group(1), match.group(2)

        if first == "":
            start, end = max(0, size - int(last)), size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1

        chunk = data[start : end + 1]
        context.status_code = 206
        context.headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        context.headers["Content-Length"] = str(len(chunk))

        return chunk

    return _callback


@pytest.fixture
def archive_url(requests_mock):
    """Serve a test data file over a mocked URL.

    Mirrors production, where archives are fetched by URL from the same host.
    Returns a callable that registers a data file and yields its URL.
    """

    def register(name: str) -> str:
        with open(os.path.join(DATA_DIR, name), "rb") as fp:
            data = fp.read()

        url = BASE_URL + name
        requests_mock.get(url, content=_range_response(data))

        return url

    return register


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
def test_build_tree(archive_url, file_format: str, num_nodes: int):
    url = archive_url(f"test_archive.{file_format}")

    adapter = utils.get_adapter_for_resource({"format": file_format})
    adapter_instance = adapter({}, {}, filepath=url)  # type: ignore
    tree = adapter_instance.build_archive_tree()

    assert len(tree) == num_nodes
    assert isinstance(tree[0], types.Node)


def test_build_complex_tree(archive_url):
    url = archive_url("test_complex_nested.zip")

    adapter = utils.get_adapter_for_resource({"format": "zip"})
    adapter_instance = adapter({}, {}, filepath=url) # type: ignore
    tree = adapter_instance.build_archive_tree()

    assert len(tree) == 15004
    root_folders = [node for node in tree if node.parent == "#"]
    assert len(root_folders) == 4
