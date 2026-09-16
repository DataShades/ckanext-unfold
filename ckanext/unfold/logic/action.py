from __future__ import annotations

from typing import Any

from ckan import types
from ckan.logic import validate
from ckan.logic.action.get import resource_view_show as _core_resource_view_show
from ckan.plugins import toolkit as tk

import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.index as unf_index
import ckanext.unfold.jobs as unf_jobs
import ckanext.unfold.logic.schema as unf_schema
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils


VIEW_TYPE = "unfold_view"


@tk.side_effect_free
@validate(unf_schema.get_archive_structure)
def get_archive_structure(
    context: types.Context, data_dict: dict[str, str]
) -> dict[str, Any]:
    """Return archive tree nodes for the jstree widget.

    The archive URL and format are read from the resource itself (via
    ``resource_show``, which also enforces authorization) rather than from the
    request, so the caller cannot point the server at an arbitrary URL.

    Two modes, decided by ``ckanext.unfold.expand_nodes_threshold``:

    * ``full`` - archives with at most that many entries: every node is
      returned flat (with ``parent``) and opened.
    * ``lazy`` - larger archives: only the direct children of ``parent``
      (default ``#``, the root) are returned, at most ``limit`` of them
      (default ``ckanext.unfold.page_size``); ``children_total`` and
      ``has_more`` tell the widget whether to offer a "show more" row.
      Folders carry ``children: true`` and are requested when opened.

    Returns ``{"error": message}`` when the archive cannot be read.
    """
    try:
        resource, resource_view = _load_resource_and_view(context, data_dict)
        index = unf_utils.get_archive_index(resource, resource_view)
    except unf_exception.UnfoldError as e:
        return {"error": str(e)}

    if index.total <= unf_config.get_expand_nodes_threshold():
        return {
            "mode": "full",
            "total": index.total,
            "nodes": [_serialize_node(n, opened=True) for n in index.all_nodes()],
        }

    parent = data_dict.get("parent") or unf_index.ROOT
    limit = int(data_dict.get("limit") or unf_config.get_page_size())
    children = index.children_of(parent)

    return {
        "mode": "lazy",
        "total": index.total,
        "parent": parent,
        "children_total": len(children),
        "has_more": len(children) > limit,
        "nodes": [
            _serialize_node(n, opened=False, flat=False) for n in children[:limit]
        ],
    }


@tk.side_effect_free
@validate(unf_schema.search_archive_structure)
def search_archive_structure(
    context: types.Context, data_dict: dict[str, Any]
) -> dict[str, Any]:
    """Find entries whose path contains ``q``.

    Returns the first ``limit`` matching entries (``results``, each with
    its full path), the folder ids that must be opened to reveal them
    (``ids``, parents before children), the total number of matches, and
    whether the result was truncated.
    """
    try:
        resource, resource_view = _load_resource_and_view(context, data_dict)
        index = unf_utils.get_archive_index(resource, resource_view)
    except unf_exception.UnfoldError as e:
        return {"error": str(e)}

    limit = data_dict.get("limit") or unf_index.DEFAULT_SEARCH_LIMIT
    result = index.search(data_dict["q"], limit)

    return {
        "ids": result.ids,
        "matches": result.matches,
        "truncated": result.truncated,
        "results": [
            {
                "id": n.id,
                "text": n.text,
                "icon": n.icon,
                "is_dir": n.icon == unf_index.FOLDER_ICON,
                "size": str(n.data.get("size") or ""),
                "modified_at": str(n.data.get("modified_at") or ""),
            }
            for n in result.results
        ],
    }


def _load_resource_and_view(
    context: types.Context, data_dict: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    resource = tk.get_action("resource_show")(context, {"id": data_dict["id"]})
    resource_view: dict[str, Any] = {}

    if data_dict.get("view_id"):
        # The core action directly, bypassing `resource_view_show` below:
        # this needs the real `archive_pass` to unlock the archive server
        # side, which is exactly what that chained action strips for anyone
        # without `resource_update` -- the password itself never reaches the
        # caller either way, only the resulting listing does.
        resource_view = _core_resource_view_show(context, {"id": data_dict["view_id"]})

        if resource_view.get("resource_id") != resource["id"]:
            raise unf_exception.UnfoldError(tk._("View does not belong to resource"))

    return resource, resource_view


@tk.chained_action
@tk.side_effect_free
def resource_view_show(
    next_action: types.Action, context: types.Context, data_dict: dict[str, Any]
) -> dict[str, Any]:
    """Strip ``archive_pass`` from an Unfold view for anyone who cannot edit it.

    ``resource_view_show`` is a public, read-only action: CKAN's dictization
    merges the view's ``config`` (where the password lives, see
    ``logic/schema.py``) straight into the returned dict, so without this,
    anyone who can read the resource could read the archive's password back
    out through this action.
    """
    view = next_action(context, data_dict)
    _strip_password_if_unauthorized(context, view)
    return view


@tk.chained_action
@tk.side_effect_free
def resource_view_list(
    next_action: types.Action, context: types.Context, data_dict: dict[str, Any]
) -> list[dict[str, Any]]:
    """Same as ``resource_view_show`` above, for the list action."""
    views = next_action(context, data_dict)

    for view in views:
        _strip_password_if_unauthorized(context, view)

    return views


@tk.chained_action
def resource_view_create(
    next_action: types.Action, context: types.Context, data_dict: dict[str, Any]
) -> dict[str, Any]:
    """Warm the archive index cache as soon as an Unfold view is added."""
    view = next_action(context, data_dict)

    if view.get("view_type") == VIEW_TYPE:
        unf_jobs.enqueue_cache_warm(view["resource_id"], view["id"])

    return view


@tk.chained_action
def resource_view_update(
    next_action: types.Action, context: types.Context, data_dict: dict[str, Any]
) -> dict[str, Any]:
    """Same as ``resource_view_create`` above: a changed ``archive_pass``
    invalidates the cached index (see ``cache_version``), so re-warm it.
    """
    view = next_action(context, data_dict)

    if view.get("view_type") == VIEW_TYPE:
        unf_jobs.enqueue_cache_warm(view["resource_id"], view["id"])

    return view


def _strip_password_if_unauthorized(
    context: types.Context, view: dict[str, Any]
) -> None:
    if view.get("view_type") != VIEW_TYPE or not view.get("archive_pass"):
        return

    try:
        tk.check_access("resource_update", context, {"id": view["resource_id"]})
    except tk.NotAuthorized:
        view["archive_pass"] = None


def _serialize_node(
    node: unf_types.Node, opened: bool, flat: bool = True
) -> dict[str, Any]:
    """Turn a node into jstree JSON.

    ``text`` is the plain entry name and ``size``/``modified_at`` stay in
    ``data`` as plain strings.
    """
    result: dict[str, Any] = {
        "id": node.id,
        "text": node.text,
        "icon": node.icon,
        "parent": node.parent,
        "state": {"opened": opened},
        "data": node.data,
        "li_attr": node.li_attr,
        "a_attr": node.a_attr,
        "children": node.children,
    }

    if flat:
        result["children"] = False
    else:
        # children of one folder are returned nested under it; jstree must
        # not try to resolve `parent` ids that are not part of the payload
        result.pop("parent", None)

    return result
