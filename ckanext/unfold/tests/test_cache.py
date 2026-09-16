"""The Redis index cache and its use by ``get_archive_index``."""

from dataclasses import asdict

import pytest

from ckanext.unfold import config, index, utils
from ckanext.unfold.tests.helpers import BASE_URL, range_response, read_fixture
from ckanext.unfold.types import Node


def _node(path: str, folder: bool = False) -> Node:
    parts = [p for p in path.split("/") if p]

    return Node(
        id=path,
        text=parts[-1],
        icon=index.FOLDER_ICON if folder else "fa fa-file",
        parent="/".join(parts[:-1]) or index.ROOT,
        data={"size": "" if folder else "1.0 KB", "modified_at": ""},
    )


@pytest.fixture
def small_index() -> index.ArchiveIndex:
    return index.ArchiveIndex.from_nodes(
        [_node("a", True), _node("a/x.txt"), _node("a/y.txt"), _node("z.txt")]
    )


def _ids(nodes: list[Node]) -> list[str]:
    return [n.id for n in nodes]


@pytest.mark.usefixtures("clean_redis")
def test_saved_index_is_read_back_field_by_field(small_index):
    utils.UnfoldCacheManager.save(small_index, "res-1", "v1")

    assert utils.UnfoldCacheManager.exists("res-1")
    assert utils.UnfoldCacheManager.total("res-1") == 4
    assert utils.UnfoldCacheManager.paths("res-1") == small_index.paths
    assert _ids(utils.UnfoldCacheManager.children("res-1", "#")) == ["a", "z.txt"]
    assert _ids(utils.UnfoldCacheManager.children("res-1", "a")) == [
        "a/x.txt",
        "a/y.txt",
    ]
    assert utils.UnfoldCacheManager.children("res-1", "missing") == []

    restored = {n.id: n for n in utils.UnfoldCacheManager.all_nodes("res-1")}
    assert restored.keys() == {n.id for n in small_index.all_nodes()}
    assert asdict(restored["a/x.txt"]) == asdict(small_index.node("a/x.txt"))


@pytest.mark.usefixtures("clean_redis")
def test_saved_index_expires(small_index):
    utils.UnfoldCacheManager.save(small_index, "res-1", "v1")

    conn = utils.UnfoldCacheManager._ensure_conn()
    ttl = conn.ttl(utils.UnfoldCacheManager._key("res-1"))

    assert 0 < ttl <= config.get_cache_ttl()


@pytest.mark.usefixtures("clean_redis")
def test_missing_and_deleted_entries(small_index):
    assert not utils.UnfoldCacheManager.exists("nope")
    assert utils.UnfoldCacheManager.total("nope") == 0
    assert utils.UnfoldCacheManager.children("nope", "#") == []
    assert utils.UnfoldCacheManager.paths("nope") == []
    assert utils.UnfoldCacheManager.all_nodes("nope") == []

    utils.UnfoldCacheManager.save(small_index, "res-1", "v1")
    utils.UnfoldCacheManager.save(small_index, "res-2", "v1")
    utils.UnfoldCacheManager.delete("res-1")

    assert not utils.UnfoldCacheManager.exists("res-1")
    assert utils.UnfoldCacheManager.exists("res-2")


@pytest.mark.usefixtures("clean_redis")
def test_saving_again_replaces_the_old_index(small_index):
    utils.UnfoldCacheManager.save(small_index, "res-1", "v1")
    utils.UnfoldCacheManager.save(
        index.ArchiveIndex.from_nodes([_node("only.txt")]), "res-1", "v2"
    )

    assert utils.UnfoldCacheManager.total("res-1") == 1
    assert utils.UnfoldCacheManager.children("res-1", "a") == []
    assert _ids(utils.UnfoldCacheManager.all_nodes("res-1")) == ["only.txt"]


@pytest.mark.usefixtures("clean_redis")
def test_cached_index_answers_like_the_in_memory_index(small_index):
    utils.UnfoldCacheManager.save(small_index, "res-1", "v1")
    cached = utils.CachedIndex("res-1")

    assert cached.total == small_index.total
    assert _ids(cached.children_of("#")) == _ids(small_index.children_of("#"))
    assert set(_ids(cached.all_nodes())) == set(_ids(small_index.all_nodes()))

    for query in ("txt", "A", "zzz"):
        expected = small_index.search(query, limit=1)
        result = cached.search(query, limit=1)

        assert (result.ids, result.matches, result.truncated) == (
            expected.ids,
            expected.matches,
            expected.truncated,
        )
        assert _ids(result.results) == _ids(expected.results)


@pytest.fixture
def tar_resource(requests_mock):
    """A tar resource: the adapter downloads it whole, so every build is
    one request."""
    url = BASE_URL + "test_archive.tar"
    requests_mock.get(url, content=range_response(read_fixture("test_archive.tar")))

    return {"id": "res-cache", "format": "tar", "url": url}


@pytest.mark.usefixtures("clean_redis", "with_request_context")
def test_index_is_built_once_then_served_from_redis(requests_mock, tar_resource):
    first = utils.get_archive_index(tar_resource, {})
    assert isinstance(first, index.ArchiveIndex)
    assert requests_mock.call_count == 1

    second = utils.get_archive_index(tar_resource, {})
    assert isinstance(second, utils.CachedIndex)
    assert requests_mock.call_count == 1

    assert second.total == first.total == 5
    assert _ids(second.children_of("sample-1")) == _ids(first.children_of("sample-1"))


@pytest.mark.ckan_config("ckanext.unfold.enable_cache", False)
@pytest.mark.usefixtures("clean_redis", "with_request_context")
def test_disabled_cache_rebuilds_on_every_call(requests_mock, tar_resource):
    for _ in range(2):
        built = utils.get_archive_index(tar_resource, {})
        assert isinstance(built, index.ArchiveIndex)

    assert requests_mock.call_count == 2
    assert not utils.UnfoldCacheManager.exists(tar_resource["id"])


def test_cache_version_changes_with_anything_that_affects_the_tree():
    base = {"url": "a.zip", "format": "zip", "metadata_modified": "2024-01-01"}
    baseline = utils.cache_version(base, {})

    assert utils.cache_version(dict(base), {}) == baseline, "not deterministic"
    assert utils.cache_version({**base, "url": "b.zip"}, {}) != baseline
    assert utils.cache_version({**base, "format": "tar"}, {}) != baseline
    assert (
        utils.cache_version({**base, "metadata_modified": "2024-06-01"}, {})
        != baseline
    )
    assert utils.cache_version(base, {"archive_pass": "secret"}) != baseline


@pytest.mark.usefixtures("clean_redis")
def test_cache_manager_version_is_none_until_saved(small_index):
    assert utils.UnfoldCacheManager.version("res-1") is None

    utils.UnfoldCacheManager.save(small_index, "res-1", "v1")
    assert utils.UnfoldCacheManager.version("res-1") == "v1"


@pytest.mark.usefixtures("clean_redis")
def test_entries_saved_before_this_field_existed_read_back_as_no_version(small_index):
    """An old-format entry (no ``version`` in ``meta``) must be treated as a
    miss, not misread as matching whatever the caller compares it to."""
    utils.UnfoldCacheManager.save(small_index, "res-1", "v1")

    conn = utils.UnfoldCacheManager._ensure_conn()
    conn.hset(utils.UnfoldCacheManager._key("res-1"), "meta", '{"total": 4}')

    assert utils.UnfoldCacheManager.version("res-1") is None


@pytest.mark.usefixtures("clean_redis", "with_request_context")
def test_edits_outside_resource_update_still_invalidate_the_cache(
    requests_mock, tar_resource
):
    """The real BUG-6 regression, using the field that actually catches it.

    ``metadata_modified``, not ``last_modified``: CKAN only bumps
    ``last_modified`` from inside the upload code, when a request submits
    a real file - a harvester re-syncing a link resource whose *remote*
    content changed behind an unchanged URL, or any plain field edit,
    never touches it. ``metadata_modified`` is bumped on any change to the
    resource, so it is the field that actually stands in for "something
    happened that this cache might not reflect".
    """
    first = utils.get_archive_index(tar_resource, {})
    assert isinstance(first, index.ArchiveIndex)
    assert requests_mock.call_count == 1

    cached = utils.get_archive_index(tar_resource, {})
    assert isinstance(cached, utils.CachedIndex)
    assert requests_mock.call_count == 1

    changed = {**tar_resource, "metadata_modified": "2030-01-01T00:00:00"}
    rebuilt = utils.get_archive_index(changed, {})

    assert isinstance(rebuilt, index.ArchiveIndex), (
        "a changed metadata_modified must force a rebuild, not serve the old cache"
    )
    assert requests_mock.call_count == 2

    # a different view (different password) of the *same*, unchanged
    # resource must not reuse a tree built for a different password either
    rebuilt_for_other_view = utils.get_archive_index(
        tar_resource, {"archive_pass": "secret"}
    )
    assert isinstance(rebuilt_for_other_view, index.ArchiveIndex)
    assert requests_mock.call_count == 3
