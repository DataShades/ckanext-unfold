from __future__ import annotations

import logging

from ar import Archive, ArchiveError
from ar.archive import ArPath

import ckanext.unfold.types as unf_types
from ckanext.unfold.adapters.base import BaseAdapter

log = logging.getLogger(__name__)


class ArAdapter(BaseAdapter):
    open_errors = (ArchiveError,)

    def iter_entries(self) -> list[unf_types.Entry]:
        """List an ar archive's entries. ar archives have no directories."""
        with self.get_file_object() as fp:
            archive = Archive(fp)

            return [self._to_entry(e) for e in archive.entries]

    @staticmethod
    def _to_entry(entry: ArPath) -> unf_types.Entry:
        return unf_types.Entry(
            path=entry.name.rstrip("/"), is_dir=False, size=entry.size
        )
