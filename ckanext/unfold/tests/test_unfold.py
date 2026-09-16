"""Adapter-level tests: every format over a mocked HTTP server."""

import io
import re
import zipfile

import py7zr
import pytest
import rarfile

from ckanext.unfold import exception, types, utils
from ckanext.unfold.adapters import remote
from ckanext.unfold.adapters.base import BaseAdapter
from ckanext.unfold.adapters.zip import ZipAdapter
from ckanext.unfold.tests import snapshots
from ckanext.unfold.tests.helpers import (
    BASE_URL,
    FORMAT_NODE_COUNTS,
    assert_valid_tree,
    build_tree,
    range_rejecting_response,
    range_response,
    read_fixture,
    summarize,
)

ZIP64_ENTRIES = 65_536  # zipfile switches to ZIP64 records above 65,535 entries


@pytest.fixture
def archive_url(requests_mock):
    """Serve a test data file over a mocked URL.

    Mirrors production, where archives are fetched by URL from the same host.
    Returns a callable that registers a data file and yields its URL.
    """

    def register(name: str) -> str:
        url = BASE_URL + name
        requests_mock.get(url, content=range_response(read_fixture(name)))

        return url

    return register


@pytest.fixture
def serve(requests_mock):
    """Serve arbitrary bytes under a name and return the URL."""

    def register(name: str, data: bytes) -> str:
        url = BASE_URL + name
        requests_mock.get(url, content=range_response(data))

        return url

    return register


@pytest.mark.usefixtures("with_request_context")
@pytest.mark.parametrize(("file_format", "num_nodes"), FORMAT_NODE_COUNTS.items())
def test_build_tree(archive_url, file_format: str, num_nodes: int):
    tree = build_tree(file_format, archive_url(f"test_archive.{file_format}"))

    assert_valid_tree(tree)
    assert len(tree) == num_nodes


@pytest.mark.usefixtures("with_request_context")
@pytest.mark.parametrize("file_format", snapshots.NODES)
def test_listing_matches_snapshot(archive_url, file_format: str):
    """Ids, parents, icons, sizes and dates of every small fixture, per format."""
    tree = build_tree(file_format, archive_url(f"test_archive.{file_format}"))

    assert summarize(tree) == snapshots.NODES[file_format]


@pytest.mark.usefixtures("with_request_context")
@pytest.mark.parametrize(("file_format", "num_nodes"), [("rar", 13), ("cbr", 38)])
def test_rar_listing_needs_no_external_tool(
    archive_url, monkeypatch, file_format: str, num_nodes: int
):
    """rarfile parses RAR3 and RAR5 headers itself; unrar, unar and bsdtar
    are only consulted to extract compressed entries.

    CI installs none of them, so the adapter must never reach for one.
    """

    def no_tool(*args, **kwargs):
        raise rarfile.RarCannotExec("Cannot find working tool")

    monkeypatch.setattr(rarfile, "tool_setup", no_tool)

    tree = build_tree(file_format, archive_url(f"test_archive.{file_format}"))

    assert len(tree) == num_nodes


def test_rar_crypto_backend_is_available():
    """A RAR5 archive with encrypted filenames (not just file contents)
    cannot be listed at all without a crypto backend (``rarfile.NoCrypto``);
    ``cryptography`` is declared for exactly this, so it must actually wire
    up. There is no such fixture to exercise end to end (creating one needs
    a real ``rar`` binary, which nothing in CI provides), so this pins the
    one signal rarfile exposes for "a backend is importable and usable".
    """
    assert rarfile._have_crypto != 0, (
        "no AES backend available to rarfile; is `cryptography` installed?"
    )


@pytest.mark.usefixtures("with_request_context")
def test_build_complex_tree(archive_url):
    tree = build_tree("zip", archive_url("test_complex_nested.zip"))

    assert_valid_tree(tree)
    assert len(tree) == 15004
    assert len([node for node in tree if node.parent == "#"]) == 4


@pytest.mark.usefixtures("with_request_context")
def test_duplicate_zip_entries_do_not_reach_the_tree_twice(serve):
    """A directory entry duplicated in the zip must not become two nodes.

    ``zipfile`` reads back exactly what it warns about writing, and real
    JARs built by tools that merge multiple archives (shading/uber-jars)
    routinely duplicate ``META-INF/`` this way. Two nodes sharing an id
    would reach jstree, whose model is indexed by id and cannot represent
    that - `assert_valid_tree`'s uniqueness check is what a browser-side
    ``children.push is not a function`` looks like server-side.
    """
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("META-INF/", "")
        archive.writestr("META-INF/MANIFEST.MF", "manifest")
        archive.writestr("META-INF/", "")  # duplicate, legal in the zip format
        archive.writestr("com/foo/Bar.class", "class bytes")

    tree = build_tree("zip", serve("dup.zip", buf.getvalue()))

    assert_valid_tree(tree)
    assert {node.id for node in tree} == {
        "META-INF",
        "META-INF/MANIFEST.MF",
        "com",
        "com/foo",
        "com/foo/Bar.class",
    }


# --- corrupt input -----------------------------------------------------------


def _corrupt_cases():
    """(format, body) for a truncated, a garbage and an empty body per format."""
    for fmt in FORMAT_NODE_COUNTS:
        data = read_fixture(f"test_archive.{fmt}")
        bodies = {
            "half": data[: len(data) // 2],
            "garbage": b"\x00garbage" * 100,
            "empty": b"",
        }

        for label, body in bodies.items():
            yield pytest.param(fmt, body, id=f"{fmt}-{label}")


@pytest.mark.usefixtures("with_request_context")
@pytest.mark.parametrize(("file_format", "body"), _corrupt_cases())
def test_corrupt_input_is_reported_or_listed(serve, file_format: str, body: bytes):
    """A damaged archive either lists what is readable or raises UnfoldError.

    Whatever happens, the caller must never see a raw library exception,
    because only ``UnfoldError`` reaches the user as a message - catching
    that specific type (and nothing broader) is what this test leans on;
    a raw library exception would propagate past it and fail the test.
    Truncated gzip and xz tars (``EOFError``) and corrupt rpms
    (``RPMError``, ``struct.error``) are the cases that rely on the
    generic wrapper.
    """
    url = serve(f"broken.{file_format}", body)

    try:
        tree = build_tree(file_format, url)
    except exception.UnfoldError as e:
        assert str(e), "UnfoldError raised with an empty message"
    else:
        if tree:
            assert_valid_tree(tree)


# --- passwords ---------------------------------------------------------------


@pytest.mark.usefixtures("with_request_context")
def test_password_protected_zip_lists_without_password(archive_url):
    """Zip encrypts entry data, not names, so the listing needs no password."""
    tree = build_tree("zip", archive_url("test_archive_pass.zip"))

    assert_valid_tree(tree)
    assert len(tree) == 13


def _encrypted_7z(header_encryption: bool) -> bytes:
    buf = io.BytesIO()

    with py7zr.SevenZipFile(
        buf,
        "w",
        password="secret",  # noqa: S106
        header_encryption=header_encryption,
    ) as archive:
        archive.writestr(b"hello", "dir/hello.txt")

    return buf.getvalue()


@pytest.mark.usefixtures("with_request_context")
def test_7z_with_encrypted_entries_is_rejected_with_a_message(serve):
    url = serve("secret.7z", _encrypted_7z(header_encryption=False))

    with pytest.raises(exception.UnfoldError, match="protected with password"):
        build_tree("7z", url)


@pytest.mark.usefixtures("with_request_context")
def test_7z_with_encrypted_headers_is_rejected_with_a_message(serve):
    url = serve("secret-headers.7z", _encrypted_7z(header_encryption=True))

    with pytest.raises(exception.UnfoldError, match="protected with password"):
        build_tree("7z", url)


class ExplodingAdapter(ZipAdapter):
    def get_node_list(self):
        raise RuntimeError("library internals")


@pytest.mark.usefixtures("with_request_context")
def test_unexpected_library_errors_become_unfold_errors(caplog):
    resource = {"id": "res-boom", "format": "zip", "url": BASE_URL + "boom.zip"}

    with (
        caplog.at_level("ERROR", logger="ckanext.unfold.adapters.base"),
        pytest.raises(
            exception.UnfoldError, match="Could not read the archive"
        ) as info,
    ):
        ExplodingAdapter(resource, {}).build_archive_tree()

    assert isinstance(info.value.__cause__, RuntimeError)
    assert "res-boom" in caplog.text
    assert "RuntimeError: library internals" in caplog.text


# --- resource metadata -------------------------------------------------------


def test_tabledesigner_resources_are_rejected():
    resource = {"format": "zip", "url": BASE_URL + "x", "type": "tabledesigner"}

    with pytest.raises(exception.UnfoldError, match="Table Designer"):
        ZipAdapter(resource, {})


@pytest.mark.ckan_config("ckanext.unfold.max_file_size", 1024)
@pytest.mark.usefixtures("with_request_context")
def test_declared_size_over_limit_is_rejected_before_download(requests_mock):
    """Formats that need the whole file trust the resource's size first."""
    url = BASE_URL + "big.tar"
    requests_mock.get(url, content=b"")

    resource = {"format": "tar", "url": url, "size": "2048"}
    adapter = utils.get_adapter_for_resource(resource)
    assert adapter is not None

    with pytest.raises(exception.UnfoldError, match="exceeds maximum allowed"):
        adapter(resource, {}).build_archive_tree()

    assert requests_mock.call_count == 0


@pytest.mark.ckan_config("ckanext.unfold.max_file_size", 1024)
@pytest.mark.usefixtures("with_request_context")
def test_unparsable_declared_size_is_ignored(archive_url):
    url = archive_url("test_archive.deb")
    resource = {"format": "deb", "url": url, "size": "unknown"}
    adapter = utils.get_adapter_for_resource(resource)
    assert adapter is not None

    # the deb fixture is 1.4 MB, so the download itself hits the limit:
    # the declared size was ignored, not the limit
    with pytest.raises(exception.UnfoldError, match="exceeds maximum allowed"):
        adapter(resource, {}).build_archive_tree()


@pytest.mark.ckan_config("ckanext.unfold.max_file_size", 1024)
@pytest.mark.usefixtures("with_request_context")
def test_full_download_rejects_advertised_content_length(requests_mock):
    url = BASE_URL + "big.tar"
    requests_mock.get(url, content=b"x" * 2048, headers={"Content-Length": "2048"})

    with pytest.raises(exception.UnfoldError, match="exceeds maximum allowed"):
        build_tree("tar", url)


@pytest.mark.ckan_config("ckanext.unfold.max_file_size", 1024)
@pytest.mark.usefixtures("with_request_context")
def test_full_download_aborts_stream_without_content_length(requests_mock):
    url = BASE_URL + "big.tar"
    # no Content-Length header: only the streaming guard can catch it
    requests_mock.get(url, content=b"x" * 2048)

    with pytest.raises(exception.UnfoldError, match="exceeds maximum allowed"):
        build_tree("tar", url)


@pytest.mark.usefixtures("with_request_context")
def test_http_error_becomes_unfold_error(requests_mock):
    url = BASE_URL + "missing.tar"
    requests_mock.get(url, status_code=404)

    with pytest.raises(exception.UnfoldError, match="Could not fetch archive"):
        build_tree("tar", url)


# --- zip: reading only the central directory ---------------------------------


@pytest.mark.usefixtures("with_request_context")
def test_zip_falls_back_to_full_download_on_416(requests_mock):
    """A server that 416s the suffix-range request still builds the tree."""
    url = BASE_URL + "test_archive.zip"
    requests_mock.get(
        url, content=range_rejecting_response(read_fixture("test_archive.zip"))
    )

    tree = build_tree("zip", url)

    assert_valid_tree(tree)
    assert len(tree) == 11


def _zip_with_long_names(entries: int, name_length: int = 150) -> bytes:
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as archive:
        for i in range(entries):
            archive.writestr(f"dir{i % 10}/{'n' * name_length}{i}", b"x")

    return buf.getvalue()


@pytest.mark.usefixtures("with_request_context")
def test_zip_directory_larger_than_one_block_is_fetched_on_demand(requests_mock):
    """The first request grabs the tail block; a directory that starts before
    it is fetched with one more forward Range request, not a full download."""
    data = _zip_with_long_names(2000)
    assert len(data) > 2 * remote.BLOCK_SIZE

    url = BASE_URL + "wide.zip"
    requests_mock.get(url, content=range_response(data))

    tree = build_tree("zip", url)

    assert_valid_tree(tree)
    assert len(tree) == 2010  # 2000 files + 10 inferred folders

    ranges = [r.headers["Range"] for r in requests_mock.request_history]
    assert ranges[0] == f"bytes=-{remote.BLOCK_SIZE}"
    assert len(ranges) == 2
    assert re.fullmatch(r"bytes=\d+-\d+", ranges[1])


@pytest.mark.usefixtures("with_request_context")
def test_zip_smaller_than_one_block_needs_a_single_request(requests_mock):
    data = _zip_with_long_names(500)
    assert len(data) < remote.BLOCK_SIZE

    url = BASE_URL + "narrow.zip"
    requests_mock.get(url, content=range_response(data))

    tree = build_tree("zip", url)

    assert len(tree) == 510
    assert requests_mock.call_count == 1


def _zip64_archive(entries: int = ZIP64_ENTRIES, payload: bytes = b"x" * 200) -> bytes:
    """Build a ZIP64 archive in memory (flat entries, ~16 MB, ~3.3 MB directory)."""
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for i in range(entries):
            z.writestr(str(i), payload)

    return buf.getvalue()


def _bytes_requested(history, size: int) -> int:
    """Sum the bytes covered by the Range headers of recorded requests."""
    total = 0

    for request in history:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", request.headers.get("Range", ""))

        if not match:
            total += size
        elif match.group(1) == "":
            total += min(int(match.group(2)), size)
        else:
            end = int(match.group(2)) if match.group(2) else size - 1
            total += end - int(match.group(1)) + 1

    return total


@pytest.mark.usefixtures("with_request_context")
def test_zip64_remote_reads_only_the_central_directory(requests_mock):
    """A ZIP64 archive is listed by fetching its directory, not the file.

    The resource claims a size far above the limit (as a harvester recording
    a 95 GB archive would); that must not block a partial read.
    """
    data = _zip64_archive()
    url = BASE_URL + "big.zip"
    requests_mock.get(url, content=range_response(data))

    resource = {"format": "zip", "url": url, "size": str(95 * 1024**3)}
    adapter = utils.get_adapter_for_resource(resource)
    assert adapter is not None
    tree = adapter(resource, {}).build_archive_tree()

    assert len(tree) == ZIP64_ENTRIES
    assert all(node.parent == "#" for node in tree)

    fetched = _bytes_requested(requests_mock.request_history, len(data))
    assert fetched < len(data) // 2
    assert all(r.headers.get("Range") for r in requests_mock.request_history)


@pytest.mark.ckan_config("ckanext.unfold.max_file_size", 1024 * 1024)
@pytest.mark.usefixtures("with_request_context")
def test_zip_limit_applies_to_bytes_transferred(requests_mock, archive_url):
    """The size limit caps what is downloaded, not the archive's size."""
    # ~3.3 MB directory exceeds a 1 MB limit even though only the tail is read
    data = _zip64_archive()
    url = BASE_URL + "big.zip"
    requests_mock.get(url, content=range_response(data))

    with pytest.raises(exception.UnfoldError, match="exceeds maximum allowed"):
        build_tree("zip", url)

    # a small archive is unaffected by the same limit
    tree = build_tree("zip", archive_url("test_archive.zip"))
    assert len(tree) == 11


@pytest.mark.usefixtures("with_request_context")
def test_zip_server_ignoring_range_falls_back_to_full_body(requests_mock):
    """A plain 200 answer (Range ignored) is parsed as the whole file."""
    data = read_fixture("test_archive.zip")
    url = BASE_URL + "test_archive.zip"
    requests_mock.get(url, content=data, headers={"Content-Length": str(len(data))})

    tree = build_tree("zip", url)

    assert len(tree) == 11


@pytest.mark.ckan_config("ckanext.unfold.max_file_size", 1024)
@pytest.mark.usefixtures("with_request_context")
def test_zip_server_ignoring_range_is_capped(requests_mock):
    """Without Range support the whole body counts against the limit."""
    url = BASE_URL + "test_archive.zip"
    # no Content-Length: the streaming guard must catch it
    requests_mock.get(url, content=read_fixture("test_archive.zip"))

    with pytest.raises(exception.UnfoldError, match="exceeds maximum allowed"):
        build_tree("zip", url)


def test_ensure_dir_entries_infers_missing_folders():
    """The shared base-class synthesis every adapter's ``build_nodes`` uses."""
    entries = [
        types.Entry(path="a/b/c.txt", is_dir=False),
        types.Entry(path="a/d.txt", is_dir=False),
        types.Entry(path="e", is_dir=True),
    ]

    result = BaseAdapter._ensure_dir_entries(entries)
    by_path = {e.path: e.is_dir for e in result}

    assert by_path == {
        "a/b/c.txt": False,
        "a/d.txt": False,
        "e": True,
        "a": True,
        "a/b": True,
    }


def test_remote_range_file_reads_across_blocks(requests_mock):
    data = bytes(range(256)) * 40  # 10,240 bytes
    url = BASE_URL + "blob"
    requests_mock.get(url, content=range_response(data))

    remote_file = remote.RemoteRangeFile(
        url, len(data), max_bytes=len(data), block_size=4096
    )

    remote_file.seek(4000)
    # crosses a block boundary, but the whole span comes in one request,
    # aligned outwards to block boundaries (0 .. 8191)
    assert remote_file.read(300) == data[4000:4300]
    assert remote_file.requests_made == 1
    assert remote_file.bytes_fetched == 8192

    assert remote_file.seek(-16, io.SEEK_END) == len(data) - 16
    assert remote_file.read() == data[-16:]
    assert remote_file.requests_made == 2
    assert remote_file.bytes_fetched == len(data)  # last (partial) block

    # already-fetched bytes are served from memory
    remote_file.seek(100)
    assert remote_file.read(50) == data[100:150]
    assert remote_file.requests_made == 2
