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

# A ZIP central directory lives at the end of the file, so we only fetch the
# tail. 64KiB covers the EOCD record (its comment is capped at 65535 bytes)
# plus the central directory of most archives; larger directories grow the
# window on demand.
INITIAL_TAIL_SIZE = 65536
TAIL_GROWTH_FACTOR = 4


class ZipAdapter(BaseAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        try:
            file_list = self.get_file_list_from_url(self.filepath)
        except (LargeZipFile, BadZipFile) as e:
            raise unf_exception.UnfoldError(f"Error opening archive: {e}") from e

        return [self._build_node(entry) for entry in self.ensure_dir_entries(file_list)]

    def get_file_list_from_url(self, url: str) -> list[ZipInfo]:
        """Read the ZIP central directory from a remote URL.

        Only the tail of the archive is downloaded via an HTTP suffix range.
        If the central directory is larger than the fetched tail, the window
        is grown and re-fetched until it parses or the whole file is read.
        Servers that ignore ``Range`` return the full file, which is parsed
        as-is.
        """
        size = INITIAL_TAIL_SIZE

        while True:
            content, total, ranged = self._fetch_tail(url, size)

            try:
                return ZipFile(BytesIO(content)).infolist()
            except BadZipFile:
                # A truncated central directory raises BadZipFile. Grow the
                # window unless we already hold the entire file.
                if not ranged or len(content) >= total or size >= total:
                    raise

                size = min(size * TAIL_GROWTH_FACTOR, total)

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

    def _fetch_tail(self, url: str, size: int) -> tuple[bytes, int, bool]:
        """Fetch the last ``size`` bytes of a remote file.

        Returns the fetched content, the total file size, and whether the
        server honored the Range request. When ranges are unsupported the
        server returns the whole file (HTTP 200) and the flag is ``False``.

        The total size is checked against the configured maximum before the
        body is downloaded, so an over-limit archive is rejected without
        pulling its contents (relevant when the server ignores ``Range``).
        """
        try:
            with requests.get(
                url,
                headers={"Range": f"bytes=-{size}"},
                timeout=DEFAULT_TIMEOUT,
                stream=True,
            ) as resp:
                resp.raise_for_status()

                ranged = resp.status_code == 206

                if ranged:
                    total = self._total_size_from_content_range(
                        resp.headers.get("content-range")
                    )
                else:
                    # Server ignored Range; the body is the whole file.
                    total = self._content_length(resp.headers.get("content-length"))

                self.enforce_size_limit(total)

                content = resp.content
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        return content, total if total is not None else len(content), ranged

    @staticmethod
    def _total_size_from_content_range(content_range: str | None) -> int | None:
        """Extract the total file size from a Content-Range header value.

        e.g. "bytes 200-1023/1024" -> 1024.
        """
        if not content_range or "/" not in content_range:
            return None

        total = content_range.rsplit("/", 1)[-1].strip()

        return int(total) if total.isdigit() else None

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
