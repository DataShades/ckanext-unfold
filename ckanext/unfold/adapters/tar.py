from __future__ import annotations

import bz2
import gzip
import io
import logging
import lzma
from tarfile import TarError, TarInfo
from tarfile import open as tar_open
from typing import IO

import ckan.plugins.toolkit as tk

import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
from ckanext.unfold.adapters.base import BaseAdapter
from ckanext.unfold.formatting import datetime_from_timestamp

log = logging.getLogger(__name__)


class _BoundedReader(io.RawIOBase):
    """Wraps a (possibly decompressing) file object, aborting once more than
    ``budget`` bytes have been read from it.

    tarfile reads a compressed tar's data blocks even when it only skips
    past them on the way to the next header, so a small compressed archive
    that inflates to a huge size still costs real CPU and memory to walk.
    Wrapping the *decompressed* stream -- rather than the raw bytes, which
    ``max_file_size`` already bounds -- lets that read abort before the
    decompression finishes.
    """

    def __init__(self, fileobj: IO[bytes], budget: int) -> None:
        super().__init__()
        self._fileobj = fileobj
        self._budget = budget
        self._read = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int | None = -1) -> bytes:
        chunk = self._fileobj.read(-1 if size is None else size)
        self._read += len(chunk)

        if self._read > self._budget:
            raise unf_exception.UnfoldError(
                tk._("Archive decompresses to more than the allowed size"),
                code=unf_exception.TOO_LARGE,
            )

        return chunk

    def tell(self) -> int:
        return self._read


class TarAdapter(BaseAdapter):
    open_errors = (TarError,)

    @staticmethod
    def _decompress(fileobj: IO[bytes]) -> IO[bytes]:
        """Build a decompressing file object from the raw compressed bytes.

        Plain, uncompressed tar: nothing to decompress.
        """
        return fileobj

    def iter_entries(self) -> list[unf_types.Entry]:
        """List a tar archive's entries.

        Tar doesn't allow us to download it partially and fetch only the
        file list, because the information about each file is stored
        alongside its data rather than in one central index. Read as a
        forward-only stream (``mode="r|"``) rather than the seekable
        ``"r:"`` mode: tarfile skips a member's data by seeking a seekable
        stream, and seeking a compressed stream still decompresses
        everything up to the target internally -- bypassing the budget
        below, which only sees bytes that flow through an explicit read.
        """
        limit = unf_config.get_max_entries()
        entries: list[unf_types.Entry] = []

        with self.get_file_object() as raw:
            fileobj = self._decompress(raw)

            with tar_open(
                fileobj=_BoundedReader(fileobj, unf_config.get_max_decompressed_size()),
                mode="r|",
            ) as tar:
                for member in tar:
                    if len(entries) >= limit:
                        log.warning(
                            "Resource %s: tar archive has more than %s entries; "
                            "the rest are not shown",
                            self.resource.get("id"),
                            limit,
                        )
                        break

                    entries.append(self._to_entry(member))

        return entries

    @staticmethod
    def _to_entry(entry: TarInfo) -> unf_types.Entry:
        return unf_types.Entry(
            path=entry.name.rstrip("/"),
            is_dir=entry.isdir(),
            size=entry.size,
            mtime=datetime_from_timestamp(entry.mtime),
        )


class TarGzAdapter(TarAdapter):
    @staticmethod
    def _decompress(fileobj: IO[bytes]) -> IO[bytes]:
        return gzip.GzipFile(fileobj=fileobj)


class TarXzAdapter(TarAdapter):
    @staticmethod
    def _decompress(fileobj: IO[bytes]) -> IO[bytes]:
        return lzma.LZMAFile(fileobj)


class TarBz2Adapter(TarAdapter):
    @staticmethod
    def _decompress(fileobj: IO[bytes]) -> IO[bytes]:
        return bz2.BZ2File(fileobj)
