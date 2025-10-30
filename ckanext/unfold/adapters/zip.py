from __future__ import annotations

import logging
from datetime import datetime as dt
from io import BytesIO
from typing import Any
from zipfile import ZIP_STORED, BadZipFile, LargeZipFile, ZipFile, ZipInfo

import requests

import ckan.plugins.toolkit as tk

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.adapters.base import DEFAULT_TIMEOUT, BaseAdapter

log = logging.getLogger(__name__)


class ZipAdapter(BaseAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        try:
            if self.remote:
                file_list = self.get_file_list_from_url(self.filepath)
            else:
                with ZipFile(self.filepath) as archive:
                    # zip format do not support encrypted filenames so we don't have
                    # to check for pass protection, we have enough information from
                    # `infolist` method

                    file_list: list[ZipInfo] = archive.infolist()
        except (LargeZipFile, BadZipFile) as e:
            raise unf_exception.UnfoldError(f"Error openning archive: {e}") from e
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        return [self._build_node(entry) for entry in self.ensure_dir_entries(file_list)]

    def get_file_list_from_url(self, url: str) -> list[ZipInfo]:
        try:
            head = requests.head(url, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive headers: {e}"
            ) from e

        end = None

        if "content-length" in head.headers:
            end = int(head.headers["content-length"])

        if "content-range" in head.headers:
            end = int(head.headers["content-range"].split("/")[1])

        if not end:
            return []

        return self._get_remote_zip_infolist(url, end - 65536, end)

    def _build_node(self, entry: ZipInfo) -> unf_types.Node:
        parts = [p for p in entry.filename.split("/") if p]
        name = unf_utils.name_from_path(entry.filename)
        fmt = "folder" if entry.is_dir() else unf_utils.get_format_from_name(name)

        return unf_types.Node(
            id=entry.filename.rstrip("/") or "",
            text=unf_utils.name_from_path(entry.filename),
            icon=(
                "fa fa-folder" if entry.is_dir() else unf_utils.get_icon_by_format(fmt)
            ),
            state={"opened": True},
            parent="/".join(parts[:-1]) if parts[:-1] else "#",
            data=self._prepare_table_data(entry),
        )

    def _prepare_table_data(self, entry: ZipInfo) -> dict[str, Any]:
        return {
            "size": (
                unf_utils.printable_file_size(entry.compress_size)
                if entry.compress_size
                else ""
            ),
            "modified_at": tk.h.render_datetime(
                dt(*entry.date_time), date_format=unf_utils.DEFAULT_DATE_FORMAT
            )
            or "",
        }

    def _get_remote_zip_infolist(self, url: str, start: int, end: int) -> list[ZipInfo]:
        try:
            resp = requests.get(
                url,
                headers={"Range": f"bytes={start}-{end}"},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        return ZipFile(BytesIO(resp.content)).infolist()

    def ensure_dir_entries(self, file_list: list[ZipInfo]) -> list[ZipInfo]:
        """Ensure directory entries exist in a ZipFile infolist.

        ZIP archives may omit explicit directory entries ("dir/") and only
        contain file paths ("dir/file.txt"). Infolist() then misses those
        directories. This function infers and adds the missing ZipInfo
        entries so consumers can rely on a complete directory tree.
        """
        names = [zi.filename for zi in file_list]
        name_set = set(names)

        inferred_dirs = set()
        for name in names:
            # treat "dir/" as a dir and "dir/file" as a file
            s = name[:-1] if name.endswith("/") else name
            i = s.rfind("/")
            while i != -1:
                d = s[: i + 1]  # keep trailing slash to mark as dir
                if d not in name_set:
                    inferred_dirs.add(d)
                i = s.rfind("/", 0, i)

        if inferred_dirs:
            for d in inferred_dirs:
                zi = ZipInfo(d)
                # Mark as a directory: set Unix mode drwxr-xr-x
                zi.external_attr = 0o40755 << 16
                zi.compress_type = ZIP_STORED
                zi.file_size = 0
                file_list.append(zi)

        return file_list
