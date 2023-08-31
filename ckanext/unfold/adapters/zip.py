from __future__ import annotations

from zipfile import ZipFile, ZipInfo

import ckanext.unfold.utils as unf_utils
import ckanext.unfold.types as unf_types


def build_directory_tree(filepath: str):
    with ZipFile(filepath) as archive:
        file_list: list[ZipInfo] = archive.infolist()

    nodes: list[unf_types.Node] = []

    for entry in file_list:
        nodes.append(_build_node(entry))

    return nodes


def _build_node(entry: ZipInfo) -> unf_types.Node:
    parts = [p for p in entry.filename.split("/") if p]
    name = unf_utils.name_from_path(entry.filename)
    fmt = "folder" if entry.is_dir() else unf_utils.get_format_from_name(name)

    return unf_types.Node(
        id=entry.filename or "",
        text=_get_node_text(entry),
        icon="fa fa-folder" if entry.is_dir() else unf_utils.get_icon_by_format(fmt),
        state={"opened": True},
        parent="/".join(parts[:-1]) + "/" if parts[:-1] else "#",
    )


def _get_node_text(entry: ZipInfo):
    if entry.is_dir():
        return unf_utils.name_from_path(entry.filename)

    file_size = unf_utils.printable_file_size(entry.compress_size or 0)

    return f"{unf_utils.name_from_path(entry.filename)} ({file_size})"