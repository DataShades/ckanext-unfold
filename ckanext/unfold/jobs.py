"""Reading archives in CKAN background jobs.

Fetching and parsing an archive can take a minute, far longer than a web worker
should be tied up for. When it can, Unfold therefore does that in a background
job and hands the result to the web side through the Redis index cache:

1. A request finds no valid index (see :func:`get_index`), enqueues
   :func:`build_archive_index` and answers "processing".
2. The widget polls ``get_archive_status`` until it says ``ready`` or ``failed``.
3. The job stores the index (or the reason it could not) and the next request
   is served from Redis like any other.

The same job is enqueued ahead of time whenever something that invalidates the
cache changes (see :func:`enqueue_cache_warm`), so that usually nobody waits.
"""

from __future__ import annotations

import logging
from typing import Any

import rq
from ckan import types
from ckan.lib import jobs as ckan_jobs
from ckan.plugins import toolkit as tk

import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.index import ArchiveIndex

log = logging.getLogger(__name__)

# ``status`` values of :func:`get_status`
READY = "ready"
PROCESSING = "processing"
FAILED = "failed"
MISSING = "missing"

# States of the record kept by ``UnfoldCacheManager.claim_build``
_PENDING = "pending"

# Failures worth trying again the next time the archive is asked for: the
# origin may have been down, or something in the job broke. Every other code
# (a wrong password, an archive over the size limit, ...) comes out the same on
# every attempt, so the recorded failure is served instead of downloading the
# archive again for every visitor.
_RETRYABLE = {unf_exception.FETCH_FAILED, unf_exception.GENERIC}

# How long past the job's own timeout a pending record survives: it must
# outlive a job that is merely slow, and only vanish once the job is certainly
# gone (worker killed, queue flushed).
_PENDING_SLACK = 60


def has_worker() -> bool:
    """Whether a ``ckan jobs worker`` is listening on the default queue."""
    return bool(rq.Worker.all(queue=ckan_jobs.get_queue()))


def can_build_in_background() -> bool:
    """Whether an uncached archive should be read by a job, not the request.

    The job hands its result over through Redis, so caching has to be on; and
    without a worker the job would sit in the queue for ever, so an unattended
    queue means the request does the work itself, as it did before jobs.
    """
    return (
        unf_config.is_cache_enabled()
        and unf_config.is_background_build_enabled()
        and has_worker()
    )


def get_index(
    resource: dict[str, Any], resource_view: dict[str, Any]
) -> unf_utils.CachedIndex | ArchiveIndex:
    """The archive's index for a web request, without reading the archive
    there if a background job can do it.

    Raises :class:`~ckanext.unfold.exception.ArchiveProcessing` when the job
    has been (or already was) queued, and
    :class:`~ckanext.unfold.exception.UnfoldError` for an archive that a job
    already found to be unreadable.
    """
    cached = unf_utils.get_cached_index(resource, resource_view)

    if cached is not None:
        return cached

    if not can_build_in_background():
        return unf_utils.get_archive_index(resource, resource_view)

    status = unf_utils.UnfoldCacheManager.status(resource["id"])

    if (
        status
        and status["version"] == unf_utils.cache_version(resource, resource_view)
        and status["state"] == FAILED
        and status["error"]["code"] not in _RETRYABLE
    ):
        raise unf_exception.UnfoldError(
            status["error"]["message"], code=status["error"]["code"]
        )

    enqueue_build(resource, resource_view)

    raise unf_exception.ArchiveProcessing


def get_status(
    resource: dict[str, Any], resource_view: dict[str, Any]
) -> dict[str, Any]:
    """Where the archive's index stands, for the widget to poll. Read-only.

    ``status`` is one of:

    * ``ready`` - cached, ask for the tree;
    * ``processing`` - a job is on it;
    * ``failed`` - the job could not read the archive; ``error`` is the same
      ``{"code", "message"}`` the structure actions return;
    * ``missing`` - nothing cached and nothing running (the job's record
      expired, or caching is off): asking for the tree starts a job.
    """
    if not unf_config.is_cache_enabled():
        return {"status": MISSING}

    resource_id = resource["id"]
    version = unf_utils.cache_version(resource, resource_view)

    if unf_utils.UnfoldCacheManager.version(resource_id) == version:
        return {"status": READY}

    record = unf_utils.UnfoldCacheManager.status(resource_id)

    if record and record["version"] == version:
        if record["state"] == _PENDING:
            return {"status": PROCESSING}

        if record["state"] == FAILED:
            return {"status": FAILED, "error": record["error"]}

    return {"status": MISSING}


def enqueue_build(resource: dict[str, Any], resource_view: dict[str, Any]) -> bool:
    """Queue :func:`build_archive_index` unless a job is already on this exact
    archive. Returns whether one was queued.
    """
    resource_id = resource["id"]
    version = unf_utils.cache_version(resource, resource_view)
    timeout = unf_config.get_job_timeout()

    if not unf_utils.UnfoldCacheManager.claim_build(
        resource_id, version, timeout + _PENDING_SLACK
    ):
        return False

    try:
        tk.enqueue_job(
            build_archive_index,
            [resource_id, resource_view.get("id")],
            title=f"Unfold: read the archive of resource {resource_id}",
            rq_kwargs={"timeout": timeout},
        )
    except Exception:
        # nothing will ever resolve the claim: give it up rather than leave
        # every visitor waiting for a job that does not exist
        unf_utils.UnfoldCacheManager.release_build(resource_id, version)
        raise

    return True


def enqueue_cache_warm(resource: dict[str, Any], resource_view: dict[str, Any]) -> None:
    """Build the index of one Unfold view ahead of its first visitor.

    Called for the edges that invalidate the cache: a view was added, its
    ``archive_pass`` changed, or the resource itself did. Does nothing when
    there is nothing to warm (the index is current) or no job could do it.
    """
    if not can_build_in_background():
        return

    if unf_utils.is_index_cached(resource, resource_view):
        return

    enqueue_build(resource, resource_view)


def build_archive_index(resource_id: str, view_id: str | None = None) -> None:
    """The background job: read one archive and cache its index.

    Whatever happens, the archive's status record is settled before this
    returns, since the page is polling it: the record is dropped on success
    (the index itself is the answer then) and replaced by the failure
    otherwise. Cheap when a concurrent job got there first: the index is
    already cached then.
    """
    context: types.Context = {"ignore_auth": True}

    try:
        resource = tk.get_action("resource_show")(context, {"id": resource_id})
        resource_view = (
            tk.get_action("resource_view_show")(context, {"id": view_id})
            if view_id
            else {}
        )
    except tk.ObjectNotFound:
        log.info(
            "Unfold: resource %s or view %s no longer exists; skipping the build",
            resource_id,
            view_id,
        )
        return

    version = unf_utils.cache_version(resource, resource_view)
    manager = unf_utils.UnfoldCacheManager

    try:
        unf_utils.get_archive_index(resource, resource_view)
    except unf_exception.UnfoldError as e:
        log.warning(
            "Unfold: could not read the archive of resource %s: %s", resource_id, e
        )
        manager.fail_build(resource_id, version, e.code, str(e))
        return
    except BaseException:
        # a bug, or the job's timeout: not for the visitor to see, but they
        # must not keep waiting either. Re-raised for RQ to log and mark failed.
        manager.fail_build(
            resource_id,
            version,
            unf_exception.GENERIC,
            tk._("The archive could not be processed"),
        )
        raise

    manager.release_build(resource_id, version)
