from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import py7zr
import requests
from py7zr import FileInfo, exceptions

import ckan.plugins.toolkit as tk

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.adapters.base import BaseAdapter

log = logging.getLogger(__name__)


class SevenZipAdapter(BaseAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        try:
            if self.remote:
                file_list = self.get_file_list_from_url(self.filepath)
            else:
                with py7zr.SevenZipFile(self.filepath) as archive:
                    if archive.needs_password():
                        raise unf_exception.UnfoldError(
                            "Error. Archive is protected with password"
                        )

                    file_list: list[FileInfo] = archive.list()
        except exceptions.ArchiveError as e:
            raise unf_exception.UnfoldError(f"Error openning archive: {e}") from e
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        return [self._build_node(entry) for entry in file_list]

    def _build_node(self, entry: FileInfo) -> unf_types.Node:
        parts = [p for p in entry.filename.split("/") if p]
        name = unf_utils.name_from_path(entry.filename)
        fmt = "folder" if entry.is_directory else unf_utils.get_format_from_name(name)

        return unf_types.Node(
            id=entry.filename.rstrip("/") or "",
            text=unf_utils.name_from_path(entry.filename),
            icon=(
                "fa fa-folder"
                if entry.is_directory
                else unf_utils.get_icon_by_format(fmt)
            ),
            state={"opened": True},
            parent="/".join(parts[:-1]) if parts[:-1] else "#",
            data=self._prepare_table_data(entry),
        )

    def _prepare_table_data(self, entry: FileInfo) -> dict[str, Any]:
        name = unf_utils.name_from_path(entry.filename)
        fmt = "" if entry.is_directory else unf_utils.get_format_from_name(name)
        modified_at = tk.h.render_datetime(
            entry.creationtime, date_format=unf_utils.DEFAULT_DATE_FORMAT
        )

        return {
            "size": (
                unf_utils.printable_file_size(entry.compressed)
                if entry.compressed
                else ""
            ),
            "type": "folder" if entry.is_directory else "file",
            "format": fmt,
            "modified_at": modified_at or "--",
        }

    def get_file_list_from_url(self, url: str) -> list[FileInfo]:
        """Download an archive and fetch a file list.

        7z file doesn't allow us to download it partially
        and fetch only file list.
        """
        content = self.make_request(url)

        archive = py7zr.SevenZipFile(BytesIO(content))

        if archive.needs_password():
            raise unf_exception.UnfoldError("Error. Archive is protected with password")

        return archive.list()
