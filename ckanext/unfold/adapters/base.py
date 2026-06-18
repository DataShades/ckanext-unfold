from __future__ import annotations

import logging
from typing import Any

import requests


import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60  # seconds


class BaseAdapter:
    def __init__(
        self,
        resource: dict[str, Any],
        resource_view: dict[str, Any],
        filepath: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.resource = resource
        self.resource_view = resource_view
        self.kwargs = kwargs
        self.filepath = filepath or self._get_filepath()

    def _get_filepath(self) -> str:
        resource_url = self.resource.get("url", "")

        if self.resource.get("type") == "tabledesigner":
            raise unf_exception.UnfoldError(
                "Error. Table Designer resources are not supported"
            )

        return resource_url

    def build_archive_tree(self) -> list[unf_types.Node]:
        self.validate_size_limit()

        return self.get_node_list()

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
        if size is None:
            return

        max_size = unf_config.get_max_file_size()

        if size < max_size:
            return

        readable_size = unf_utils.printable_file_size(max_size)

        raise unf_exception.UnfoldError(
            f"Error. Archive exceeds maximum allowed size for processing: {readable_size}"
        )

    def get_file_content(self, url: str | None = None) -> bytes:
        """Download a remote file and return its content as bytes.

        Defaults to ``self.filepath`` when no URL is given. The size is
        enforced against the configured maximum: the advertised
        Content-Length is rejected up front, and the download is aborted once
        the bytes read exceed the limit (in case Content-Length is missing or
        wrong), so an over-limit archive is never fully loaded into memory.
        """
        url = url or self.filepath

        try:
            with requests.get(url, timeout=DEFAULT_TIMEOUT, stream=True) as resp:
                resp.raise_for_status()

                self.enforce_size_limit(
                    self._content_length(resp.headers.get("content-length"))
                )

                chunks: list[bytes] = []
                downloaded = 0

                for chunk in resp.iter_content(chunk_size=65536):
                    downloaded += len(chunk)
                    self.enforce_size_limit(downloaded)
                    chunks.append(chunk)
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(f"Error fetching archive: {e}") from e

        return b"".join(chunks)

    @staticmethod
    def _content_length(content_length: str | None) -> int | None:
        """Parse a Content-Length header value into an int."""
        if content_length and content_length.isdigit():
            return int(content_length)

        return None

    def get_node_list(self) -> list[unf_types.Node]:
        """Return list of nodes representing the file structure."""
        raise NotImplementedError
