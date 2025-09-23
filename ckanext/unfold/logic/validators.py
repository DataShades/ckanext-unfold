import logging
from typing import Any, Optional, Iterable, List

import ckan.plugins.toolkit as tk
import ckan.types as types

import ckanext.unfold.adapters as unf_adapters
import ckanext.unfold.exception as unf_exception

log = logging.getLogger(__name__)

__all__ = ["valid_count_and_depth", "valid_formats"]

def resource_view_id_exists(resource_view_id: str, context: types.Context) -> Any:
    """Ensures that the resource_view with a given id exists."""

    model = context["model"]
    session = context["session"]

    if not session.query(model.ResourceView).get(resource_view_id):
        raise tk.Invalid("Resource view not found.")

    return resource_view_id

 
def valid_count_and_depth(value: str) -> int:
    if value in [None, ""]:
        return None
    try: 
        value = int(value)
    except (TypeError, ValueError):
        raise tk.Invalid(f"'{value}' is not a valid integer.")
    if value < 1:
        raise tk.Invalid(f"Config values for 'max_size', 'max_count', 'max_nested_count' and 'max_depth' must be >= 1, got: {value}")
    return value


def valid_formats(value: Optional[Iterable[str] | str]) -> List[str]:
    supported = set(unf_adapters.ADAPTERS.keys())
    if value is None:
        return sorted(supported)

    if isinstance(value, str):
        formats = [f.strip().lower() for f in value.split() if f.strip()]
    else:
        formats = [str(f).strip().lower() for f in value if str(f).strip()]

    unsupported = [f for f in formats if f not in supported]
    if unsupported:
        log.warning(
            "Unsupported formats in config: %s. Supported formats: %s",
            unsupported, sorted(supported)
        )
    normalized = [f for f in formats if f in supported]
    return normalized

