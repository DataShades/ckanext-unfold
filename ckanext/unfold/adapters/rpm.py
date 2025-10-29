from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import requests
from rpmfile import RPMFile, RPMInfo

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.adapters.base import BaseAdapter

log = logging.getLogger(__name__)


class RpmAdapter(BaseAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        try:
            if self.remote:
                file_list = self.get_file_list_from_url(self.filepath)
            else:
                with RPMFile(self.filepath, "rb") as archive:
                    file_list: list[RPMInfo] = archive.getmembers()
        except (NotImplementedError, KeyError) as e:
            raise unf_exception.UnfoldError(f"Error openning archive: {e}") from e
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        nodes = [self._build_node(entry) for entry in file_list]

        return self._add_folder_nodes(nodes)

    def _build_node(self, entry: RPMInfo) -> unf_types.Node:
        parts = [p for p in entry.name.split("/") if p]
        name = unf_utils.name_from_path(entry.name)
        fmt = "folder" if entry.isdir else unf_utils.get_format_from_name(name)

        return unf_types.Node(
            id=entry.name.rstrip("/") or "",
            text=unf_utils.name_from_path(entry.name),
            icon="fa fa-folder" if entry.isdir else unf_utils.get_icon_by_format(fmt),
            parent="/".join(parts[:-1]) if parts[:-1] else "#",
            data=self._prepare_table_data(entry),
        )

    def _prepare_table_data(self, entry: RPMInfo) -> dict[str, Any]:
        name = unf_utils.name_from_path(entry.name)
        fmt = "" if entry.isdir else unf_utils.get_format_from_name(name)

        return {
            "size": unf_utils.printable_file_size(entry.size) if entry.size else "",
            "type": "folder" if entry.isdir else "file",
            "format": fmt,
            "modified_at": "--",  # rpmfile doesn't provide this info
        }

    def get_file_list_from_url(self, url: str) -> list[RPMInfo]:
        """Download an archive and fetch a file list.

        Tar file doesn't allow us to download it partially
        and fetch only file list, because the information
        about each file is stored at the beggining of the file
        """
        content = self.make_request(url)

        return RPMFile(fileobj=BytesIO(content)).getmembers()

    def _add_folder_nodes(self, nodes: list[unf_types.Node]) -> list[unf_types.Node]:
        folder_nodes: dict[str, unf_types.Node] = {}

        for node in nodes:
            if node.parent == "#":
                continue

            self._build_parent_node(node.parent, folder_nodes)

        return nodes + list(folder_nodes.values())

    def _build_parent_node(
        self, parent: str, nodes: dict[str, unf_types.Node]
    ) -> dict[str, unf_types.Node]:
        parts = [p for p in parent.split("/") if p]

        if not parts:
            return nodes

        bottom = parent == "."

        nodes.setdefault(
            parent,
            unf_types.Node(
                id=parent,
                text=parent,
                icon="fa fa-folder",
                parent="#" if bottom else "/".join(parts[:-1]),
                data={
                    "size": "",
                    "type": "folder",
                    "format": "",
                    "modified_at": "--",
                },
            ),
        )

        if not bottom:
            self._build_parent_node("/".join(parts[:-1]), nodes)

        return nodes
