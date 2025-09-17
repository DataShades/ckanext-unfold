from __future__ import annotations

import logging
from datetime import datetime as dt
from io import BytesIO
from typing import Any, Optional

import rarfile
import requests
from rarfile import Error as RarError
from rarfile import RarInfo

import ckan.plugins.toolkit as tk

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils

log = logging.getLogger(__name__)


def build_directory_tree(
    filepath: str, resource_view: dict[str, Any], remote: Optional[bool] = False
) -> list[unf_types.Node]:
    try:
        if remote:
            file_list = get_rarlist_from_url(filepath)
        else:
            with rarfile.RarFile(filepath) as archive:
                if archive.needs_password() and not resource_view.get("archive_pass"):
                    raise unf_exception.UnfoldError(
                        "Error. Archive is protected with password"
                    )
                elif archive.needs_password():
                    archive.setpassword(resource_view["archive_pass"])

                file_list: list[RarInfo] = archive.infolist()
    except RarError as e:
        raise unf_exception.UnfoldError(f"Error openning archive: {e}")
    except requests.RequestException as e:
        raise unf_exception.UnfoldError(f"Error fetching remote archive: {e}")

    if not file_list:
        raise unf_exception.UnfoldError(
            "Error. The archive is either empty or the password is incorrect."
        )

    nodes: list[unf_types.Node] = []

    for entry in file_list:
        nodes.append(_build_node(entry))

    return nodes


def _build_node(entry: RarInfo) -> unf_types.Node:
    parts = [p for p in entry.filename.split("/") if p]
    name = unf_utils.name_from_path(entry.filename)
    fmt = "" if entry.isdir() else unf_utils.get_format_from_name(name)

    return unf_types.Node(
        id=entry.filename.rstrip("/") or "",
        text=unf_utils.name_from_path(entry.filename),
        icon="fa fa-folder" if entry.isdir() else unf_utils.get_icon_by_format(fmt),
        state={"opened": True},
        parent="/".join(parts[:-1]) if parts[:-1] else "#",
        data=_prepare_table_data(entry),
    )


def _prepare_table_data(entry: RarInfo) -> dict[str, Any]:
    name = unf_utils.name_from_path(entry.filename)
    fmt = "" if entry.isdir() else unf_utils.get_format_from_name(name)

    return {
        "size": (
            unf_utils.printable_file_size(entry.compress_size)
            if entry.compress_size
            else "--"
        ),
        "type": "folder" if entry.isdir() else "file",
        "format": fmt,
        "modified_at": _fetch_mtime(entry),
    }


def _fetch_mtime(entry: RarInfo) -> str:
    modified_at = tk.h.render_datetime(
        entry.mtime, date_format=unf_utils.DEFAULT_DATE_FORMAT
    )

    if not modified_at and isinstance(entry.date_time, tuple):
        modified_at = tk.h.render_datetime(
            dt(*entry.date_time),  # type: ignore
            date_format=unf_utils.DEFAULT_DATE_FORMAT,
        )

    return modified_at or "--"


def get_rarlist_from_url(url) -> list[RarInfo]:
    """Download an archive and fetch a file list. Rar file doesn't allow us
    to download it partially and fetch only file list."""
    resp = requests.get(url, timeout=unf_utils.DEFAULT_TIMEOUT)

    archive = rarfile.RarFile(BytesIO(resp.content))

    if archive.needs_password():
        raise unf_exception.UnfoldError("Error. Archive is protected with password")

    return archive.infolist()
