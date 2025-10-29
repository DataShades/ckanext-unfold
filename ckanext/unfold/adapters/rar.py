from __future__ import annotations

import logging
from datetime import datetime as dt
from io import BytesIO
from typing import Any

import rarfile
import requests
from rarfile import Error as RarError
from rarfile import RarInfo

import ckan.plugins.toolkit as tk

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.adapters.base import BaseAdapter

log = logging.getLogger(__name__)


class RarAdapter(BaseAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        try:
            if self.remote:
                file_list = self.get_file_list_from_url(self.filepath)
            else:
                with rarfile.RarFile(self.filepath) as archive:
                    needs_password = archive.needs_password()

                    if needs_password and not self.resource_view.get("archive_pass"):
                        raise unf_exception.UnfoldError(
                            "Error. Archive is protected with password"
                        )

                    if needs_password:
                        archive.setpassword(self.resource_view["archive_pass"])

                    file_list: list[RarInfo] = archive.infolist()
        except RarError as e:
            raise unf_exception.UnfoldError(f"Error openning archive: {e}") from e
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        if not file_list:
            raise unf_exception.UnfoldError(
                "Error. The archive is either empty or the password is incorrect."
            )

        return [self._build_node(entry) for entry in file_list]


    def get_file_list_from_url(self, url: str) -> list[RarInfo]:
        """Download an archive and fetch a file list.

        Rar file doesn't allow us to download it partially and fetch only file list.
        """
        content = self.make_request(url)

        archive = rarfile.RarFile(BytesIO(content))

        if archive.needs_password():
            raise unf_exception.UnfoldError("Error. Archive is protected with password")

        return archive.infolist()

    def _build_node(self, entry: RarInfo) -> unf_types.Node:
        filename = entry.filename or ""
        parts = [p for p in filename.split("/") if p]
        name = unf_utils.name_from_path(filename)
        fmt = "" if entry.isdir() else unf_utils.get_format_from_name(name)

        return unf_types.Node(
            id=filename.rstrip("/") or "",
            text=unf_utils.name_from_path(filename),
            icon="fa fa-folder" if entry.isdir() else unf_utils.get_icon_by_format(fmt),
            state={"opened": True},
            parent="/".join(parts[:-1]) if parts[:-1] else "#",
            data=self._prepare_table_data(entry),
        )

    def _prepare_table_data(self, entry: RarInfo) -> dict[str, Any]:
        name = unf_utils.name_from_path(entry.filename)
        fmt = "" if entry.isdir() else unf_utils.get_format_from_name(name)

        return {
            "size": (
                unf_utils.printable_file_size(entry.compress_size)
                if entry.compress_size
                else ""
            ),
            "type": "folder" if entry.isdir() else "file",
            "format": fmt,
            "modified_at": self._fetch_mtime(entry),
        }

    def _fetch_mtime(self, entry: RarInfo) -> str:
        modified_at = tk.h.render_datetime(
            entry.mtime, date_format=unf_utils.DEFAULT_DATE_FORMAT
        )

        if not modified_at and isinstance(entry.date_time, tuple):
            modified_at = tk.h.render_datetime(
                dt(*entry.date_time),  # type: ignore
                date_format=unf_utils.DEFAULT_DATE_FORMAT,
            )

        return modified_at or "--"
