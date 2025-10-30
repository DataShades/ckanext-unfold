from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import requests
from ar import Archive, ArchiveError
from ar.archive import ArPath

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.adapters.base import BaseAdapter

log = logging.getLogger(__name__)


class ArAdapter(BaseAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        try:
            if self.remote:
                file_list = self.get_file_list_from_url(self.filepath)
            else:
                with open(self.filepath, "rb") as file:
                    archive = Archive(file)
                    file_list: list[ArPath] = archive.entries
        except ArchiveError as e:
            raise unf_exception.UnfoldError(f"Error openning archive: {e}") from e
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        return [self._build_node(entry) for entry in file_list]

    def _build_node(self, entry: ArPath) -> unf_types.Node:
        parts = [p for p in entry.name.split("/") if p]
        name = unf_utils.name_from_path(entry.name)

        return unf_types.Node(
            id=entry.name.rstrip("/") or "",
            text=unf_utils.name_from_path(entry.name),
            icon=unf_utils.get_icon_by_format(unf_utils.get_format_from_name(name)),
            parent="/".join(parts[:-1]) if parts[:-1] else "#",
            data=self._prepare_table_data(entry),
        )

    def _prepare_table_data(self, entry: ArPath) -> dict[str, Any]:
        return {
            "size": (unf_utils.printable_file_size(entry.size) if entry.size else ""),
            "modified_at": "",
        }

    def get_file_list_from_url(self, url: str) -> list[ArPath]:
        """Download an archive and fetch a file list."""
        content = self.make_request(url)

        try:
            archive = Archive(BytesIO(content))
        except ArchiveError as e:
            raise unf_exception.UnfoldError(f"Error openning archive: {e}") from e

        return archive.entries
