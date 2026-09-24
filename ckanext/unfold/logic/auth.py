from __future__ import annotations

from typing import Any

import ckan.plugins.toolkit as tk
from ckan import authz, types


@tk.auth_allow_anonymous_access
def get_archive_structure(
    context: types.Context, data_dict: dict[str, Any]
) -> types.AuthResult:
    """Anyone who can see the resource may browse its archive."""
    return _can_show_resource(context, data_dict)


@tk.auth_allow_anonymous_access
def search_archive_structure(
    context: types.Context, data_dict: dict[str, Any]
) -> types.AuthResult:
    return _can_show_resource(context, data_dict)


@tk.auth_allow_anonymous_access
def get_archive_status(
    context: types.Context, data_dict: dict[str, Any]
) -> types.AuthResult:
    return _can_show_resource(context, data_dict)


def rebuild_archive_index(
    context: types.Context, data_dict: dict[str, Any]
) -> types.AuthResult:
    """Anyone who can edit the resource may have its archive read again."""
    return authz.is_authorized("resource_update", context, {"id": data_dict.get("id")})


def _can_show_resource(
    context: types.Context, data_dict: dict[str, Any]
) -> types.AuthResult:
    return authz.is_authorized("resource_show", context, {"id": data_dict.get("id")})
