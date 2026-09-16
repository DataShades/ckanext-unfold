from __future__ import annotations

import logging
from io import BytesIO

import py7zr
from py7zr import FileInfo, exceptions

import ckan.plugins.toolkit as tk

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
from ckanext.unfold.adapters.base import BaseAdapter

log = logging.getLogger(__name__)


class SevenZipAdapter(BaseAdapter):
    def get_node_list(self) -> list[unf_types.Node]:
        try:
            entries = self.iter_entries()
        except exceptions.PasswordRequired as e:
            # raised on open when the header itself is encrypted; not an
            # ArchiveError subclass
            raise unf_exception.UnfoldError(
                tk._("Archive is protected with password")
            ) from e
        except exceptions.ArchiveError as e:
            raise unf_exception.UnfoldError(
                tk._("Could not open archive: %(error)s") % {"error": e}
            ) from e

        return self.build_nodes(entries)

    def iter_entries(self) -> list[unf_types.Entry]:
        """List a 7z archive's entries.

        7z doesn't allow us to download it partially and fetch only the
        file list.
        """
        content = self.get_file_content()
        password = self.resource_view.get("archive_pass") or None
        archive = py7zr.SevenZipFile(BytesIO(content), password=password)


        if archive.needs_password() and not password:
            raise unf_exception.UnfoldError(tk._("Archive is protected with password"))

        return [self._to_entry(info) for info in archive.list()]

    @staticmethod
    def _to_entry(entry: FileInfo) -> unf_types.Entry:
        return unf_types.Entry(
            path=entry.filename.rstrip("/"),
            is_dir=entry.is_directory,
            size=entry.compressed,
            mtime=entry.creationtime,
        )
