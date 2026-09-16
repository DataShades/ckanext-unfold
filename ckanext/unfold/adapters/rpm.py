from __future__ import annotations

import logging

from rpmfile import RPMFile, RPMInfo

import ckanext.unfold.types as unf_types
from ckanext.unfold.adapters.base import BaseAdapter

log = logging.getLogger(__name__)


class RpmAdapter(BaseAdapter):
    open_errors = (NotImplementedError, KeyError)

    def iter_entries(self) -> list[unf_types.Entry]:
        """List an RPM's entries.

        Tar doesn't allow us to download it partially and fetch only the
        file list, because the information about each file is stored at the
        beginning of the file. RPM's cpio payload also never includes
        explicit directory entries, so every ancestor folder is synthesized
        by the base class.
        """
        with self.get_file_object() as fp:
            members = RPMFile(fileobj=fp).getmembers()

            return [self._to_entry(m) for m in members]

    @staticmethod
    def _to_entry(entry: RPMInfo) -> unf_types.Entry:
        return unf_types.Entry(
            path=entry.name.rstrip("/"), is_dir=bool(entry.isdir), size=entry.size
        )
