"""Reading locally uploaded resources through CKAN's uploader."""

import pytest

import ckan.plugins as p
from ckan.tests import factories

from ckanext.unfold import exception, utils
from ckanext.unfold.adapters import base
from ckanext.unfold.tests.helpers import (
    BASE_URL,
    assert_valid_tree,
    range_response,
    read_fixture,
)

try:
    from ckan.lib import files
except ImportError:  # CKAN < 2.12: no file-keeper storage layer
    files = None  # type: ignore[assignment]

needs_file_keeper = pytest.mark.skipif(
    files is None, reason="needs CKAN 2.12's file-keeper storage layer"
)

ARCHIVE = read_fixture("test_archive.zip")


@pytest.mark.usefixtures("clean_db", "with_request_context")
def test_upload_is_read_through_ckan_storage(create_with_upload):
    """A resource uploaded through CKAN's own configured uploader is read
    back through it too (file-keeper storage on 2.12+, a local path via
    the legacy uploader on 2.11), instead of requesting its own download
    URL (which fails for private datasets)."""
    dataset = factories.Dataset()
    resource = create_with_upload(
        read_fixture("test_archive.zip"),
        "test_archive.zip",
        package_id=dataset["id"],
        format="zip",
    )
    assert resource["url_type"] == "upload"

    adapter = utils.get_adapter_for_resource(resource)
    assert adapter is not None
    tree = adapter(resource, {}).build_archive_tree()

    assert_valid_tree(tree)
    assert len(tree) == 11


class LegacyResourceUpload:
    """What ``ResourceUpload`` and third-party ``IUploader`` plugins such as
    ckanext-cloudstorage or ckanext-s3filestore provide: a path, no
    ``storage`` attribute."""

    def __init__(self, path: str) -> None:
        self.path = path

    def get_path(self, resource_id: str) -> str:
        return self.path

    def upload(self, resource_id: str, max_size: int = 10) -> None:
        pass


class LegacyUploaderPlugin(p.SingletonPlugin):
    p.implements(p.IUploader, inherit=True)

    path = ""

    def get_resource_uploader(self, data_dict):
        return LegacyResourceUpload(self.path)


@pytest.mark.with_plugins({"unfold_test_legacy_uploader": LegacyUploaderPlugin})
@pytest.mark.usefixtures("with_request_context")
def test_upload_through_uploader_without_storage_attribute(tmp_path):
    archive = tmp_path / "test_archive.zip"
    archive.write_bytes(ARCHIVE)
    LegacyUploaderPlugin.path = str(archive)

    resource = {
        "id": "res-legacy",
        "format": "zip",
        "url_type": "upload",
        "url": "test_archive.zip",
        "size": archive.stat().st_size,
    }
    adapter = utils.get_adapter_for_resource(resource)
    assert adapter is not None
    tree = adapter(resource, {}).build_archive_tree()

    assert_valid_tree(tree)
    assert len(tree) == 11


# --- one unit test per branch of ``_read_upload`` ------------------------------


def _upload_resource() -> dict:
    return {
        "id": "res-upload",
        "format": "zip",
        "url_type": "upload",
        "url": BASE_URL + "test_archive.zip",
        "size": len(ARCHIVE),
    }


def _tree_via(monkeypatch, upload) -> list:
    monkeypatch.setattr(base.uploader, "get_resource_uploader", lambda resource: upload)
    resource = _upload_resource()
    adapter = utils.get_adapter_for_resource(resource)
    assert adapter is not None

    return adapter(resource, {}).build_archive_tree()


@needs_file_keeper
@pytest.mark.usefixtures("with_request_context")
def test_file_keeper_uploader_is_read_through_its_storage(monkeypatch):
    seen = []

    class Storage:
        def content(self, data):
            seen.append(data.location)
            return ARCHIVE

    class Uploader:
        storage = Storage()

        def get_path(self, resource_id):
            return f"res/-up/{resource_id[6:]}"

    tree = _tree_via(monkeypatch, Uploader())

    assert_valid_tree(tree)
    assert len(tree) == 11
    assert seen == ["res/-up/load"]


@needs_file_keeper
@pytest.mark.usefixtures("with_request_context")
def test_storage_errors_are_reported(monkeypatch):
    class Storage:
        def content(self, data):
            raise files.exc.FilesError("gone")

    class Uploader:
        storage = Storage()

        def get_path(self, resource_id):
            return "somewhere"

    with pytest.raises(exception.UnfoldError, match="Could not read uploaded archive"):
        _tree_via(monkeypatch, Uploader())


@pytest.mark.usefixtures("with_request_context")
def test_legacy_uploader_is_read_from_its_local_path(
    monkeypatch, tmp_path, requests_mock
):
    archive = tmp_path / "abc" / "def" / "ghi"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(ARCHIVE)

    tree = _tree_via(monkeypatch, LegacyResourceUpload(str(archive)))

    assert_valid_tree(tree)
    assert len(tree) == 11
    assert requests_mock.call_count == 0


@pytest.mark.usefixtures("with_request_context")
def test_uploader_without_local_file_falls_back_to_download(monkeypatch, requests_mock):
    """Cloud uploaders return a bucket key from ``get_path``; the resource
    URL is the only way left to reach the bytes."""
    requests_mock.get(BASE_URL + "test_archive.zip", content=range_response(ARCHIVE))

    tree = _tree_via(monkeypatch, LegacyResourceUpload("resources/abc/def/ghi"))

    assert_valid_tree(tree)
    assert len(tree) == 11
    assert requests_mock.call_count == 1


@pytest.mark.usefixtures("with_request_context")
def test_uploader_whose_get_path_fails_falls_back_to_download(
    monkeypatch, requests_mock
):
    """``ResourceUpload`` raises TypeError when ``ckan.storage_path`` is unset."""
    requests_mock.get(BASE_URL + "test_archive.zip", content=range_response(ARCHIVE))

    class Uploader:
        def get_path(self, resource_id):
            raise TypeError("storage_path is not defined")

    tree = _tree_via(monkeypatch, Uploader())

    assert len(tree) == 11
    assert requests_mock.call_count == 1


@pytest.mark.usefixtures("with_request_context")
def test_download_fallback_reports_http_failures(monkeypatch, requests_mock):
    requests_mock.get(BASE_URL + "test_archive.zip", status_code=403)

    with pytest.raises(exception.UnfoldError, match="Could not fetch archive"):
        _tree_via(monkeypatch, LegacyResourceUpload("resources/abc/def/ghi"))


@pytest.mark.usefixtures("with_request_context")
def test_storage_attribute_is_ignored_without_file_keeper(monkeypatch, tmp_path):
    """Simulates CKAN < 2.12, where `ckan.lib.files` does not exist.

    Even an uploader that happens to expose `.storage` (a custom IUploader
    plugin written against the file-keeper API) must not be read through it
    on an older CKAN that never imported the module the data it returns
    would be typed against; the local-path branch is what a legacy CKAN
    install actually relies on.
    """
    monkeypatch.setattr(base, "files", None)

    archive = tmp_path / "abc" / "def" / "ghi"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(ARCHIVE)

    class Storage:
        def content(self, data):
            raise AssertionError("storage.content must not be called")

    class Uploader:
        storage = Storage()

        def get_path(self, resource_id):
            return str(archive)

    tree = _tree_via(monkeypatch, Uploader())

    assert_valid_tree(tree)
    assert len(tree) == 11
