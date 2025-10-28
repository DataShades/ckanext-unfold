from __future__ import annotations

import logging
from typing import Any

import ckanext.unfold.types as unf_types

log = logging.getLogger(__name__)


class BaseAdapter:
    def build_directory_tree(
        self, filepath: str, resource_view: dict[str, Any], remote: bool | None = False
    ) -> list[unf_types.Node]:
        raise NotImplementedError
