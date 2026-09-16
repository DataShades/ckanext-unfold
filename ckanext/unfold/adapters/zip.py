from __future__ import annotations

import logging
from zipfile import BadZipFile, LargeZipFile, ZipFile, ZipInfo

import ckanext.unfold.config as unf_config
import ckanext.unfold.types as unf_types
from ckanext.unfold.adapters import remote
from ckanext.unfold.adapters.base import BaseAdapter
from ckanext.unfold.formatting import datetime_from_dos

log = logging.getLogger(__name__)


class ZipAdapter(BaseAdapter):
    # Remote archives are opened through a Range-backed reader; only the
    # central directory is transferred, so the resource's declared size is
    # not a reason to refuse the preview.
    partial_read = True
    open_errors = (LargeZipFile, BadZipFile)

    def iter_entries(self) -> list[unf_types.Entry]:
        if self.is_upload:
            with self.get_file_object() as fp:
                infolist = ZipFile(fp).infolist()
        else:
            infolist = self._infolist_from_remote(self.filepath)

        return [self._to_entry(info) for info in infolist]

    def _infolist_from_remote(self, url: str) -> list[ZipInfo]:
        """Read the ZIP central directory from a remote URL.

        The archive is opened through a seekable, Range-backed file object,
        so ``zipfile`` fetches only the end-of-central-directory records and
        the central directory itself, wherever they sit in the file. This
        also covers ZIP64 archives (over 4 GiB or 65,535 entries): their
        locator stores absolute offsets, which is why a truncated tail can
        never be parsed on its own. The configured size limit applies to the
        bytes transferred, not to the archive size.

        Servers that ignore ``Range`` return the whole file, which is
        accepted only within the limit.
        """
        fp = remote.open_remote(
            url,
            unf_config.get_max_file_size(),
            unf_config.get_request_timeout(),
            unf_config.get_zip_tail_block_size(),
        )

        with fp, ZipFile(fp) as archive:
            return archive.infolist()

    @staticmethod
    def _to_entry(info: ZipInfo) -> unf_types.Entry:
        return unf_types.Entry(
            path=info.filename.rstrip("/"),
            is_dir=info.is_dir(),
            size=info.compress_size,
            mtime=datetime_from_dos(info.date_time),
        )
