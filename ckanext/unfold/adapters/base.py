from __future__ import annotations

import logging
from typing import Any

import requests

import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.truncate as unf_truncate
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils

log = logging.getLogger(__name__)


class BaseAdapter:
    def __init__(
        self,
        filepath: str,
        resource: dict[str, Any],
        resource_view: dict[str, Any],
        remote: bool = False,
        **kwargs: Any,
    ) -> None:
        self.filepath = filepath
        self.resource = resource
        self.resource_view = resource_view
        self.remote = remote
        self.kwargs = kwargs

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

        max_size = unf_config.get_max_size()

        if archive_size is None or archive_size < max_size:
            return

        readable_size = unf_utils.printable_file_size(max_size)

        raise unf_exception.UnfoldError(
            f"Error. Archive exceeds maximum allowed size for processing: {readable_size}"
        )

    def make_request(self, url: str) -> bytes:
        """Make a GET request to the specified URL and return the content."""
        try:
            resp = requests.get(url, timeout=unf_utils.DEFAULT_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        return resp.content

    def get_node_list(self) -> list[unf_types.Node]:
        raise NotImplementedError

    def get_file_list_from_url(self, url: str) -> list[Any]:
        raise NotImplementedError
