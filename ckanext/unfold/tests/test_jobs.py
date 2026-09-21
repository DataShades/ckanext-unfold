"""Reading archives in background jobs: the job, its status and the actions.

``tk.enqueue_job`` is replaced by a recorder and the job function is called
directly where a worker would have run it, so no RQ worker is needed. Datasets
are created outside the HTTP mock, see ``test_action.py``.
"""

import pytest

import ckan.plugins.toolkit as tk
from ckan.tests import factories
from ckan.tests.helpers import call_action

from ckanext.unfold import jobs, utils
from ckanext.unfold.logic import action
from ckanext.unfold.tests.helpers import BASE_URL, served

ARCHIVE = "test_archive.zip"
Manager = utils.UnfoldCacheManager

# The cache is on by default. It is not set with a module-level ``ckan_config``
# mark on purpose: a test's own mark for the same key would lose to it.
pytestmark = [
    pytest.mark.usefixtures(
        "with_plugins", "clean_db", "clean_redis", "with_request_context"
    ),
]


@pytest.fixture
def queued(monkeypatch) -> list[tuple[str, str | None]]:
    """Pretend a worker is listening, and record the jobs it would be given."""
    calls: list[tuple[str, str | None]] = []

    def enqueue_job(fn, args, **kwargs):
        assert fn is jobs.build_archive_index
        assert kwargs["rq_kwargs"] == {"timeout": 600}
        calls.append(tuple(args))

    monkeypatch.setattr(jobs, "has_worker", lambda: True)
    monkeypatch.setattr(jobs.tk, "enqueue_job", enqueue_job)

    return calls


@pytest.fixture
def archive_resource():
    return factories.Resource(url=BASE_URL + ARCHIVE, format="zip")


@pytest.fixture
def csv_resource():
    """A resource that no adapter reads: its job fails the same way every time."""
    return factories.Resource(url=BASE_URL + "data.csv", format="csv")


def test_uncached_archive_is_left_to_a_job(archive_resource, queued, monkeypatch):
    def read(*_, **__):
        raise AssertionError("the archive was read inside the web request")

    monkeypatch.setattr(utils, "get_archive_tree", read)

    result = call_action("get_archive_structure", id=archive_resource["id"])

    assert result == {"status": "processing"}
    assert queued == [(archive_resource["id"], None)]
    assert call_action("get_archive_status", id=archive_resource["id"]) == {
        "status": "processing"
    }


def test_visitors_share_one_job(archive_resource, queued):
    for _ in range(3):
        result = call_action("get_archive_structure", id=archive_resource["id"])
        assert result == {"status": "processing"}

    call_action("search_archive_structure", id=archive_resource["id"], q="xlsx")

    assert len(queued) == 1


def test_finished_job_makes_the_archive_ready(archive_resource, queued):
    resource_id = archive_resource["id"]
    call_action("get_archive_structure", id=resource_id)

    with served(ARCHIVE):
        jobs.build_archive_index(resource_id, None)

    assert Manager.status(resource_id) is None
    assert call_action("get_archive_status", id=resource_id) == {"status": "ready"}

    result = call_action("get_archive_structure", id=resource_id)
    assert result["mode"] == "full"
    assert result["total"] == 11
    assert len(queued) == 1


def test_job_uses_the_views_password(queued):
    """The job must fingerprint the archive exactly like the web request does,
    or the index it stores would never be found again."""
    resource = factories.Resource(url=BASE_URL + ARCHIVE, format="zip")
    view = call_action(
        "resource_view_create",
        resource_id=resource["id"],
        view_type="unfold_view",
        title="Unfold",
        archive_pass="secret",  # noqa: S106
    )
    queued.clear()

    with served(ARCHIVE):
        jobs.build_archive_index(resource["id"], view["id"])

    status = call_action("get_archive_status", id=resource["id"], view_id=view["id"])
    assert status == {"status": "ready"}

    # the same resource seen through a view with another password is a new archive
    other = call_action("get_archive_status", id=resource["id"])
    assert other == {"status": "missing"}


def test_failed_fetch_is_reported_and_tried_again(archive_resource, queued):
    resource_id = archive_resource["id"]
    call_action("get_archive_structure", id=resource_id)

    with served(ARCHIVE, b"") as mocker:
        mocker.get(BASE_URL + ARCHIVE, status_code=404)
        jobs.build_archive_index(resource_id, None)

    status = call_action("get_archive_status", id=resource_id)
    assert status["status"] == "failed"
    assert status["error"]["code"] == "fetch_failed"
    assert status["error"]["message"].startswith("Could not fetch remote archive")

    # the origin may be back: asking again queues a second job
    result = call_action("get_archive_structure", id=resource_id)
    assert result == {"status": "processing"}
    assert len(queued) == 2


def test_hopeless_failure_is_served_without_another_job(csv_resource, queued):
    resource_id = csv_resource["id"]
    call_action("get_archive_structure", id=resource_id)
    jobs.build_archive_index(resource_id, None)

    status = call_action("get_archive_status", id=resource_id)
    assert status["status"] == "failed"
    assert status["error"]["code"] == "unsupported_format"

    structure = call_action("get_archive_structure", id=resource_id)
    search = call_action("search_archive_structure", id=resource_id, q="x")

    assert structure == {"error": status["error"]}
    assert search == {"error": status["error"]}

    assert len(queued) == 1


def test_unexpected_error_is_recorded_and_reraised(
    archive_resource, queued, monkeypatch
):
    def broken(*_):
        raise RuntimeError("boom")

    monkeypatch.setattr(utils, "get_archive_index", broken)

    with pytest.raises(RuntimeError, match="boom"):
        jobs.build_archive_index(archive_resource["id"], None)

    status = call_action("get_archive_status", id=archive_resource["id"])
    assert status["status"] == "failed"
    assert status["error"]["code"] == "error"
    # nothing about the exception reaches the visitor
    assert "boom" not in status["error"]["message"]


def test_job_for_a_deleted_resource_is_a_no_op(queued):
    assert jobs.build_archive_index("no-such-resource", None) is None


def test_failure_of_an_older_state_is_not_shown(csv_resource, queued):
    resource_id = csv_resource["id"]
    call_action("get_archive_structure", id=resource_id)
    jobs.build_archive_index(resource_id, None)
    assert call_action("get_archive_status", id=resource_id)["status"] == "failed"

    call_action(
        "resource_update", id=resource_id, url=BASE_URL + "data.csv", format="csv2"
    )

    assert call_action("get_archive_status", id=resource_id) == {"status": "missing"}


def test_lost_job_can_be_requested_again(archive_resource, queued):
    resource_id = archive_resource["id"]
    call_action("get_archive_structure", id=resource_id)
    # the record expires when a worker dies mid-job
    utils.UnfoldCacheManager._ensure_conn().delete(
        utils.UnfoldCacheManager._status_key(resource_id)
    )

    assert call_action("get_archive_status", id=resource_id) == {"status": "missing"}
    assert call_action("get_archive_structure", id=resource_id) == {
        "status": "processing"
    }
    assert len(queued) == 2


def test_enqueue_failure_does_not_leave_visitors_waiting(archive_resource, monkeypatch):
    monkeypatch.setattr(jobs, "has_worker", lambda: True)

    def broken(*_, **__):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(jobs.tk, "enqueue_job", broken)

    with pytest.raises(ConnectionError):
        call_action("get_archive_structure", id=archive_resource["id"])

    assert Manager.status(archive_resource["id"]) is None


def test_without_a_worker_the_request_reads_the_archive(archive_resource, monkeypatch):
    monkeypatch.setattr(jobs, "has_worker", lambda: False)

    with served(ARCHIVE):
        result = call_action("get_archive_structure", id=archive_resource["id"])

    assert result["mode"] == "full"


@pytest.mark.ckan_config("ckanext.unfold.build_in_background", False)
def test_background_build_can_be_switched_off(archive_resource, queued):
    with served(ARCHIVE):
        result = call_action("get_archive_structure", id=archive_resource["id"])

    assert result["mode"] == "full"
    assert queued == []


@pytest.mark.ckan_config("ckanext.unfold.enable_cache", False)
def test_without_the_cache_there_is_nothing_to_hand_over(archive_resource, queued):
    with served(ARCHIVE):
        result = call_action("get_archive_structure", id=archive_resource["id"])

    assert result["mode"] == "full"
    assert queued == []
    assert call_action("get_archive_status", id=archive_resource["id"]) == {
        "status": "missing"
    }


def test_new_view_warms_the_cache_once(archive_resource, queued):
    view = call_action(
        "resource_view_create",
        resource_id=archive_resource["id"],
        view_type="unfold_view",
        title="Unfold",
    )

    assert queued == [(archive_resource["id"], view["id"])]

    # a visitor who arrives while it runs joins it
    call_action("get_archive_structure", id=archive_resource["id"], view_id=view["id"])
    assert len(queued) == 1


def test_other_views_do_not_warm_anything(archive_resource, queued):
    # only `unfold` is loaded in these tests, so no other view can be created
    action._warm_cache(
        {"view_type": "image_view", "resource_id": archive_resource["id"], "id": "v"}
    )

    assert queued == []


def test_cached_archive_is_not_warmed_again(archive_resource, queued):
    resource_id = archive_resource["id"]
    call_action("get_archive_structure", id=resource_id)

    with served(ARCHIVE):
        jobs.build_archive_index(resource_id, None)

    call_action(
        "resource_view_create",
        resource_id=resource_id,
        view_type="unfold_view",
        title="Unfold",
    )

    assert len(queued) == 1


def test_updating_the_resource_warms_the_cache(archive_resource, queued):
    view = call_action(
        "resource_view_create",
        resource_id=archive_resource["id"],
        view_type="unfold_view",
        title="Unfold",
    )
    queued.clear()

    # a new URL is a new archive, so the job claimed for the view does not cover it
    call_action("resource_patch", id=archive_resource["id"], url=BASE_URL + "other.zip")

    assert queued == [(archive_resource["id"], view["id"])]


def test_status_of_an_unknown_resource_fails_validation():
    with pytest.raises(tk.ValidationError):
        call_action("get_archive_status", id="does-not-exist")


# The status records behind all of the above


def test_only_one_claim_per_version_wins():
    assert Manager.claim_build("res", "v1", 60) is True
    assert Manager.claim_build("res", "v1", 60) is False
    assert Manager.status("res") == {"version": "v1", "state": "pending"}

    # a build of another state of the resource replaces it
    assert Manager.claim_build("res", "v2", 60) is True
    assert Manager.status("res")["version"] == "v2"


def test_claims_expire():
    Manager.claim_build("res", "v1", 60)

    assert 0 < Manager._ensure_conn().ttl(Manager._status_key("res")) <= 60


def test_failed_claim_can_be_taken_again():
    Manager.claim_build("res", "v1", 60)
    Manager.fail_build("res", "v1", "fetch_failed", "down")

    assert Manager.status("res") == {
        "version": "v1",
        "state": "failed",
        "error": {"code": "fetch_failed", "message": "down"},
    }
    assert Manager.claim_build("res", "v1", 60) is True
    assert Manager.status("res")["state"] == "pending"


def test_release_leaves_the_record_of_another_version():
    Manager.claim_build("res", "v2", 60)

    Manager.release_build("res", "v1")
    assert Manager.status("res") is not None

    Manager.release_build("res", "v2")
    assert Manager.status("res") is None


def test_deleting_the_index_deletes_its_status_too():
    Manager.claim_build("res", "v1", 60)
    Manager.delete("res")

    assert Manager.status("res") is None


def test_clear_all_removes_statuses_without_counting_them(small_index):
    Manager.save(small_index, "res-1", "v1")
    Manager.claim_build("res-2", "v1", 60)

    assert Manager.clear_all() == 1
    assert Manager.status("res-2") is None


@pytest.fixture
def small_index():
    from ckanext.unfold.index import ArchiveIndex
    from ckanext.unfold.types import Node

    return ArchiveIndex.from_nodes(
        [Node(id="a.txt", text="a.txt", icon="fa fa-file", parent="#")]
    )
