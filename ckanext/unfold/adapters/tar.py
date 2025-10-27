from __future__ import annotations

import logging
import tarfile
from datetime import datetime as dt
from io import BytesIO
from tarfile import TarError, TarFile, TarInfo
from typing import Any, Optional

import requests

import ckan.plugins.toolkit as tk

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils

log = logging.getLogger(__name__)


def build_directory_tree(
    filepath: str,
    resource_view: dict[str, Any],
    remote: Optional[bool] = False,
    compression: Optional[str] = None,
) -> list[unf_types.Node]:
    mode = "r" if not compression else f"r:{compression}"

    try:
        if remote:
            file_list = get_tarlist_from_url(filepath)
        else:
            with tarfile.open(filepath, mode) as archive: # type: ignore
                # TODO: tarfile library doesn't have built-in support
                # for checking whether a TAR file is protected with a password
                # investigate it if someone will have such a problem lately
                file_list: list[TarInfo] = archive.getmembers()
    except TarError as e:
        raise unf_exception.UnfoldError(f"Error openning archive: {e}")
    except requests.RequestException as e:
        raise unf_exception.UnfoldError(f"Error fetching remote archive: {e}")

    nodes: list[unf_types.Node] = []

    for entry in file_list:
        nodes.append(_build_node(entry))

    return nodes


def _build_node(entry: TarInfo) -> unf_types.Node:
    parts = [p for p in entry.name.split("/") if p]
    name = unf_utils.name_from_path(entry.name)
    fmt = "folder" if entry.isdir() else unf_utils.get_format_from_name(name)

    return unf_types.Node(
        id=entry.name.rstrip("/") or "",
        text=unf_utils.name_from_path(entry.name),
        icon="fa fa-folder" if entry.isdir() else unf_utils.get_icon_by_format(fmt),
        state={"opened": True},
        parent="/".join(parts[:-1]) if parts[:-1] else "#",
        data=_prepare_table_data(entry),
    )


def _prepare_table_data(entry: TarInfo) -> dict[str, Any]:
    name = unf_utils.name_from_path(entry.name)
    fmt = "" if entry.isdir() else unf_utils.get_format_from_name(name)
    modified_at = tk.h.render_datetime(
        dt.fromtimestamp(entry.mtime), date_format=unf_utils.DEFAULT_DATE_FORMAT
    )

    return {
        "size": unf_utils.printable_file_size(entry.size) if entry.size else "",
        "type": "folder" if entry.isdir() else "file",
        "format": fmt,
        "modified_at": modified_at or "--",
    }


def get_tarlist_from_url(url) -> list[TarInfo]:
    """Download an archive and fetch a file list. Tar file doesn't allow us
    to download it partially and fetch only file list, because the information
    about each file is stored at the beggining of the file"""
    resp = requests.get(url, timeout=unf_utils.DEFAULT_TIMEOUT)

    return TarFile(fileobj=BytesIO(resp.content)).getmembers()
