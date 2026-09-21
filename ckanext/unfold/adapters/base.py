from __future__ import annotations

import io
import logging
import os
from typing import IO, Any

import ckan.plugins.toolkit as tk
from ckan.lib import uploader

try:
    # CKAN >= 2.12 only: the file-keeper storage layer core absorbed from
    # ckanext-files. Older CKAN's uploaders never set `storage` (see
    # `_read_upload`), so the module is simply unused when it is missing.
    from ckan.lib import files
except ImportError:  # CKAN < 2.12
    files = None  # type: ignore[assignment]

import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
from ckanext.unfold.adapters import remote
from ckanext.unfold.formatting import (
    DEFAULT_DATE_FORMAT,
    file_icon,
    get_format_from_name,
    name_from_path,
    printable_file_size,
)

log = logging.getLogger(__name__)

__all__ = ["BaseAdapter"]


class BaseAdapter:
    #: Set to ``True`` in adapters that can read a remote archive's index
    #: without downloading the whole file (see ``remote.open_remote``). For
    #: those the resource's declared size is not checked up front; the size
    #: limit applies to the bytes actually transferred instead, so archives
    #: far larger than the limit remain previewable.
    partial_read: bool = False

    #: Exception types the underlying archive library raises while opening
    #: or parsing a damaged file; ``get_node_list`` turns any of these into
    #: a plain "Could not open archive: ..." message. An adapter that needs a
    #: different message for some errors (a password prompt, a distinct
    #: fetch failure) overrides ``get_node_list`` instead of using this.
    open_errors: tuple[type[Exception], ...] = ()

    def __init__(
        self,
        resource: dict[str, Any],
        resource_view: dict[str, Any],
        filepath: str | None = None,
    ) -> None:
        self.resource = resource
        self.resource_view = resource_view
        self.filepath = filepath or self._get_filepath()

    def _get_filepath(self) -> str:
        resource_url = self.resource.get("url", "")

        if self.resource.get("type") == "tabledesigner":
            raise unf_exception.UnfoldError(
                tk._("Table Designer resources are not supported"),
                code=unf_exception.UNSUPPORTED_FORMAT,
            )

        return resource_url

    @property
    def is_upload(self) -> bool:
        return self.resource.get("url_type") == "upload"

    @property
    def reads_partially(self) -> bool:
        """Whether this adapter will fetch only parts of the remote file."""
        return self.partial_read and not self.is_upload

    def build_archive_tree(self) -> list[unf_types.Node]:
        if not self.reads_partially:
            self.validate_size_limit()

        try:
            return self.get_node_list()
        except unf_exception.UnfoldError:
            raise
        except Exception as e:
            # Archive libraries raise their own errors (and plain ValueError,
            # struct.error, EOFError...) on damaged input. Only UnfoldError
            # reaches the user as a message; anything else would be a 500.
            log.exception(
                "Resource %s: could not read %s archive %s",
                self.resource.get("id"),
                self.resource.get("format"),
                self.filepath,
            )
            raise unf_exception.UnfoldError(
                tk._("Could not read the archive"), code=unf_exception.UNREADABLE
            ) from e

    def validate_size_limit(self) -> None:
        archive_size = self.resource.get("size")

        if archive_size and isinstance(archive_size, str):
            try:
                archive_size = int(archive_size)
            except (ValueError, TypeError):
                archive_size = None

        self.enforce_size_limit(archive_size)

    def enforce_size_limit(self, size: int | None) -> None:
        """Raise if ``size`` exceeds the configured maximum archive size.

        ``None`` means the size is unknown and is allowed through.
        """
        remote.check_limit(size, unf_config.get_max_file_size())

    def get_file_object(self, url: str | None = None) -> IO[bytes]:
        """Return the resource's content as a seekable binary file object.

        Locally uploaded resources are read straight from CKAN storage,
        avoiding an authenticated HTTP request to CKAN's own download endpoint
        (which fails for private datasets with 403). Remote resources are
        downloaded over HTTP.

        For remote downloads the size is enforced against the configured
        maximum: the advertised Content-Length is rejected up front, and the
        download is aborted once the bytes read exceed the limit (in case
        Content-Length is missing or wrong), so an over-limit archive is never
        fully transferred.
        """
        if self.is_upload:
            return self._read_upload()

        return remote.fetch_full(
            url or self.filepath,
            unf_config.get_max_file_size(),
            unf_config.get_request_timeout(),
        )

    def _read_upload(self) -> IO[bytes]:
        """Open an uploaded resource through whatever uploader serves it.

        CKAN 2.12's file-keeper uploader exposes a ``storage``; the legacy
        ``ResourceUpload`` and extensions such as ckanext-cloudstorage or
        ckanext-s3filestore only offer ``get_path``, which may name a local
        file or a key in a remote bucket. Each shape is tried in turn, ending
        with a plain download of the resource URL for uploaders that keep
        files elsewhere.

        The size is already enforced up front against the resource metadata in
        ``validate_size_limit``; the download fallback enforces it again.
        """
        upload = uploader.get_resource_uploader(self.resource)
        resource_id = self.resource["id"]
        # `files` (and thus a `storage` attribute) only exists on CKAN >= 2.12
        storage = getattr(upload, "storage", None) if files is not None else None

        if storage is not None:
            stream = getattr(storage, "stream", None)

            try:
                if stream is None:
                    data = storage.content(files.FileData(upload.get_path(resource_id)))
                    return io.BytesIO(data)

                source = stream(files.FileData(upload.get_path(resource_id)))

                if isinstance(source, io.IOBase) and source.seekable():
                    return source  # type: ignore[return-value]

                return remote.spool(source)
            except files.exc.FilesError as e:
                raise unf_exception.UnfoldError(
                    tk._("Could not read uploaded archive: %(error)s") % {"error": e},
                    code=unf_exception.FETCH_FAILED,
                ) from e

        path = self._local_upload_path(upload)

        if path is not None:
            try:
                return open(path, "rb")
            except OSError as e:
                raise unf_exception.UnfoldError(
                    tk._("Could not read uploaded archive: %(error)s") % {"error": e},
                    code=unf_exception.FETCH_FAILED,
                ) from e

        log.info(
            "Resource %s: uploader %s offers neither a storage nor a local file;"
            " downloading %s",
            resource_id,
            type(upload).__name__,
            self.filepath,
        )
        return remote.fetch_full(
            self.filepath,
            unf_config.get_max_file_size(),
            unf_config.get_request_timeout(),
        )

    def _local_upload_path(self, upload: Any) -> str | None:
        """Absolute path of the uploaded file, if the uploader keeps it on disk."""
        get_path = getattr(upload, "get_path", None)

        if get_path is None:
            return None

        try:
            path = get_path(self.resource["id"])
        except Exception:
            # ResourceUpload raises TypeError without a storage path and
            # ValidationError for ids it cannot map; neither is fatal here
            log.debug(
                "Resource %s: %s.get_path failed",
                self.resource["id"],
                type(upload).__name__,
                exc_info=True,
            )
            return None

        if isinstance(path, str) and os.path.isabs(path) and os.path.isfile(path):
            return path

        return None

    @staticmethod
    def _content_length(content_length: str | None) -> int | None:
        """Parse a Content-Length header value into an int."""
        return remote.content_length(content_length)

    def iter_entries(self) -> list[unf_types.Entry]:
        """Return this archive's entries. Implemented by every adapter.

        Each entry is a small, library-agnostic record (see ``types.Entry``);
        ``get_node_list`` turns them into ``Node`` objects.
        """
        raise NotImplementedError

    def get_node_list(self) -> list[unf_types.Node]:
        """Return list of nodes representing the file structure.

        The default implementation calls ``iter_entries`` and translates any
        exception listed in ``open_errors`` into a generic message. An
        adapter whose library raises more than one kind of error (a password
        prompt vs. a corrupt file, say) overrides this instead.
        """
        try:
            entries = self.iter_entries()
        except self.open_errors as e:
            raise unf_exception.UnfoldError(
                tk._("Could not open archive: %(error)s") % {"error": e},
                code=unf_exception.UNREADABLE,
            ) from e

        return self.build_nodes(entries)

    def build_nodes(self, entries: list[unf_types.Entry]) -> list[unf_types.Node]:
        """Turn entries into nodes, synthesizing any missing ancestor folders."""
        entries = self._enforce_entry_limit(self._dedupe_entries(entries))
        return [self._build_node(e) for e in self._ensure_dir_entries(entries)]

    @staticmethod
    def _dedupe_entries(entries: list[unf_types.Entry]) -> list[unf_types.Entry]:
        """Collapse entries that share a path to the last one.

        An archive can legitimately list the same path more than once - most
        commonly a directory entry duplicated by the tool that wrote it
        (``zipfile`` itself will happily read back what it warns about
        writing, and real JARs built by shading/merging tools routinely
        duplicate ``META-INF/`` this way), but also a file overwritten later
        in the same archive. Every tool that actually extracts an archive
        resolves that the same way: the last entry with a given name wins.

        Without this, two ``Node``s sharing an ``id`` would reach the
        browser - jstree indexes its model by id and cannot represent that,
        so the second one silently corrupts the first one's bookkeeping
        instead of raising a clean error.
        """
        deduped: dict[str, unf_types.Entry] = {}

        for entry in entries:
            deduped[entry.path.rstrip("/")] = entry

        return list(deduped.values())

    def _enforce_entry_limit(
        self, entries: list[unf_types.Entry]
    ) -> list[unf_types.Entry]:
        """Truncate to the configured maximum entry count.

        Most archive libraries parse their whole member list up front, so
        this cannot save the parsing cost for those formats -- but it does
        cap the downstream cost: millions of ``Node`` objects, a
        multi-hundred-megabyte cache entry, and a browser tab that never
        finishes rendering. Formats that can stop early (tar, see
        ``TarAdapter.iter_entries``) apply the same limit during iteration
        instead, so this is a no-op for them by the time it runs.
        """
        limit = unf_config.get_max_entries()

        if len(entries) <= limit:
            return entries

        log.warning(
            "Resource %s: archive has %s entries, more than the configured "
            "maximum of %s; the rest are not shown",
            self.resource.get("id"),
            len(entries),
            limit,
        )
        return entries[:limit]

    @staticmethod
    def _ensure_dir_entries(entries: list[unf_types.Entry]) -> list[unf_types.Entry]:
        """Synthesize directory entries missing from the entry list.

        Archives may list only file paths ("dir/file.txt") without an entry
        for "dir" itself (common for tar, 7z, rar, ar and always true for
        rpm's cpio payload). jstree and the folder index both need a real
        node for every ancestor, so every missing path segment is added here
        as a directory entry with no size or date.
        """
        names = {e.path.rstrip("/") for e in entries}
        inferred: dict[str, unf_types.Entry] = {}

        for entry in entries:
            s = entry.path.rstrip("/")
            i = s.rfind("/")

            while i != -1:
                d = s[:i]

                if d and d not in names and d not in inferred:
                    inferred[d] = unf_types.Entry(path=d, is_dir=True)

                i = s.rfind("/", 0, i)

        return [*entries, *inferred.values()]

    def _build_node(self, entry: unf_types.Entry) -> unf_types.Node:
        path = entry.path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        name = name_from_path(path)
        fmt = "folder" if entry.is_dir else get_format_from_name(name)

        return unf_types.Node(
            id=path or "",
            text=name,
            icon="fa fa-folder" if entry.is_dir else file_icon(fmt),
            parent="/".join(parts[:-1]) if parts[:-1] else "#",
            data=self._prepare_table_data(entry),
        )

    def _prepare_table_data(self, entry: unf_types.Entry) -> dict[str, Any]:
        return {
            "size": printable_file_size(entry.size) if entry.size else "",
            "modified_at": tk.h.render_datetime(
                entry.mtime, date_format=DEFAULT_DATE_FORMAT
            )
            or "",
        }
