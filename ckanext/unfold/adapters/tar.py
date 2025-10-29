from __future__ import annotations

import logging
import tarfile
from datetime import datetime as dt
from io import BytesIO
from tarfile import TarError, TarFile, TarInfo
from typing import Any

import requests

import ckan.plugins.toolkit as tk

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.adapters.base import BaseAdapter

log = logging.getLogger(__name__)


class TarAdapter(BaseAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        return self._build_directory_tree(self.filepath, self.remote, "r")

    def _build_directory_tree(
        self, filepath: str, remote: bool = False, mode: str | None = None
    ):
        try:
            if remote:
                file_list = self.get_file_list_from_url(filepath)
            else:
                with tarfile.open(filepath, mode) as archive:  # type: ignore
                    file_list: list[TarInfo] = archive.getmembers()
        except TarError as e:
            raise unf_exception.UnfoldError(f"Error openning archive: {e}") from e
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        return [self._build_node(entry) for entry in file_list]

    def _build_node(self, entry: TarInfo) -> unf_types.Node:
        parts = [p for p in entry.name.split("/") if p]
        name = unf_utils.name_from_path(entry.name)
        fmt = "folder" if entry.isdir() else unf_utils.get_format_from_name(name)

        return unf_types.Node(
            id=entry.name.rstrip("/") or "",
            text=unf_utils.name_from_path(entry.name),
            icon="fa fa-folder" if entry.isdir() else unf_utils.get_icon_by_format(fmt),
            state={"opened": True},
            parent="/".join(parts[:-1]) if parts[:-1] else "#",
            data=self._prepare_table_data(entry),
        )

    def _prepare_table_data(self, entry: TarInfo) -> dict[str, Any]:
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

    def get_file_list_from_url(self, url: str) -> list[TarInfo]:
        """Download an archive and fetch a file list.

        Tar file doesn't allow us to download it partially
        and fetch only file list, because the information
        about each file is stored at the beginning of the file
        """
        content = self.make_request(url)

        return TarFile(fileobj=BytesIO(content)).getmembers()


class TarGzAdapter(TarAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        return self._build_directory_tree(self.filepath, self.remote, "r:gz")


class TarXzAdapter(TarAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        return self._build_directory_tree(self.filepath, self.remote, "r:xz")


class TarBz2Adapter(TarAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        return self._build_directory_tree(self.filepath, self.remote, "r:bz2")
