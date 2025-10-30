from __future__ import annotations

import logging
from typing import Any

import requests

import ckan.plugins.toolkit as tk
from ckan.lib.uploader import get_resource_uploader

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

        if filepath:
            self.remote = False
            self.filepath = filepath
        else:
            self.remote = self._is_remote()
            self.filepath = self._get_filepath()

    def _get_filepath(self) -> str:
        resource_url = self.resource.get("url", "")

        if self.resource.get("type") == "tabledesigner":
            raise unf_exception.UnfoldError(
                "Error. Table Designer resources are not supported"
            )

        if self.remote:
            return resource_url

        return get_resource_uploader(self.resource).get_path(self.resource["id"])

    def _is_remote(self) -> bool:
        resource_type = self.resource.get("type", "")
        resource_url = self.resource.get("url", "")

        if not resource_url:
            raise unf_exception.UnfoldError("Resource URL is empty")

        if resource_type == "upload":
            return False

        if resource_type == "url":
            return True

        return not self.resource.get("url", "").startswith(tk.config["ckan.site_url"])

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

        max_size = unf_config.get_max_file_size()

        if archive_size is None or archive_size < max_size:
            return

        readable_size = unf_utils.printable_file_size(max_size)

        raise unf_exception.UnfoldError(
            f"Error. Archive exceeds maximum allowed size for processing: {readable_size}"
        )

    def make_request(self, url: str) -> bytes:
        """Make a GET request to the specified URL and return the content."""
        try:
            with requests.get(url, timeout=DEFAULT_TIMEOUT, stream=True) as resp:
                resp.raise_for_status()
                content = resp.content  # fully read before connection closes
        except requests.RequestException as e:
            raise unf_exception.UnfoldError(
                f"Error fetching remote archive: {e}"
            ) from e

        return content

    def get_node_list(self) -> list[unf_types.Node]:
        """Return list of nodes representing the file structure.

        Ensure, that your implementation handles both local and remote files
        based on the `self.remote` attribute.
        """
        raise NotImplementedError
