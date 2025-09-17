from __future__ import annotations

import logging
from io import BytesIO
from typing import Any, Optional

import requests
from ar import Archive
from ar.archive import Archive, ArchiveError, ArPath

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils

log = logging.getLogger(__name__)


def build_directory_tree(
    filepath: str, resource_view: dict[str, Any], remote: Optional[bool] = False
) -> list[unf_types.Node]:
    try:
        if remote:
            file_list = get_arlist_from_url(filepath)
        else:
            with open(filepath, "rb") as file:
                archive = Archive(file)
                file_list: list[ArPath] = archive.entries
    except ArchiveError as e:
        raise unf_exception.UnfoldError(f"Error openning archive: {e}")
    except requests.RequestException as e:
        raise unf_exception.UnfoldError(f"Error fetching remote archive: {e}")

    nodes: list[unf_types.Node] = []

    for entry in file_list:
        nodes.append(_build_node(entry))

    # nodes = _add_folder_nodes(nodes)

    return nodes


def _build_node(entry: ArPath) -> unf_types.Node:
    parts = [p for p in entry.name.split("/") if p]
    name = unf_utils.name_from_path(entry.name)

    return unf_types.Node(
        id=entry.name.rstrip("/") or "",
        text=unf_utils.name_from_path(entry.name),
        icon=unf_utils.get_icon_by_format(unf_utils.get_format_from_name(name)),
        parent="/".join(parts[:-1]) if parts[:-1] else "#",
        data=_prepare_table_data(entry),
    )


def _prepare_table_data(entry: ArPath) -> dict[str, Any]:
    name = unf_utils.name_from_path(entry.name)

    return {
        "size": (unf_utils.printable_file_size(entry.size) if entry.size else "--"),
        "type": "file",
        "format": unf_utils.get_format_from_name(name),
        "modified_at": "--",
    }


def get_arlist_from_url(url) -> list[ArPath]:
    """Download an archive and fetch a file list"""
    resp = requests.get(url, timeout=unf_utils.DEFAULT_TIMEOUT)

    try:
        archive = Archive(BytesIO(resp.content))
    except ArchiveError as e:
        raise unf_exception.UnfoldError(f"Error openning archive: {e}")

    return archive.entries
