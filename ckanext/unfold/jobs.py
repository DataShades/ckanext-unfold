from __future__ import annotations

import logging

from ckan import types
from ckan.plugins import toolkit as tk

import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.utils as unf_utils

log = logging.getLogger(__name__)


def enqueue_cache_warm(resource_id: str, view_id: str) -> None:
    """Schedule :func:`build_archive_index` for one Unfold view, if caching
    is on. A no-op with caching off: there would be nothing to warm.
    """
    if not unf_config.is_cache_enabled():
        return

    tk.enqueue_job(
        build_archive_index,
        [resource_id, view_id],
        title=f"Unfold: warm archive index cache for resource {resource_id}",
    )


def build_archive_index(resource_id: str, view_id: str) -> None:
    """Warm the Redis cache for one archive view, off the request path.

    Enqueued when an Unfold view is created and whenever something that
    invalidates the cache changes (the resource itself, or the view's
    password).

    Without this, the fetch-and-parse of a large archive runs synchronously
    inside the first visitor's web request.
    """
    context: types.Context = {"ignore_auth": True}

    try:
        resource = tk.get_action("resource_show")(context, {"id": resource_id})
        resource_view = tk.get_action("resource_view_show")(context, {"id": view_id})
    except tk.ObjectNotFound:
        log.info(
            "Unfold: resource %s or view %s no longer exists; skipping cache warm",
            resource_id,
            view_id,
        )
        return

    try:
        unf_utils.get_archive_index(resource, resource_view)
    except unf_exception.UnfoldError as e:
        log.warning(
            "Unfold: could not warm the cache for resource %s: %s", resource_id, e
        )
