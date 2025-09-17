import logging
import re
from typing import Any, Callable, Optional

import ckan.plugins.toolkit as tk

import ckanext.unfold.adapters as unf_adapters
import ckanext.unfold.exception as unf_exception

log = logging.getLogger(__name__)


def parse_size_config(size_str: Optional[str]) -> Optional[int]:
    if not size_str or not size_str.strip():
        return None  # Default: no limit

    size_str = size_str.strip().upper()

    # Match pattern like '50MB', '1.5GB', etc.
    match = re.match(r"^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)$", size_str)
    if not match:
        raise unf_exception.UnfoldError(
            f"Invalid size format: '{size_str}'. Expected format: <number><unit> "
            f"where unit is B, KB, MB, or GB (e.g., '50MB', '1GB')"
        )

    value, unit = match.groups()
    try:
        value = float(value)
    except ValueError:
        raise unf_exception.UnfoldError(f"Invalid numeric value in size: '{size_str}'")

    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}

    return int(value * multipliers[unit])


def parse_max_depth(value: Optional[str]) -> Optional[int]:
    if not value:
        return None  # Default: no limit

    try:
        depth = int(value)
        if depth < 1:
            raise unf_exception.UnfoldError(f"Max depth must be >= 1, got: {depth}")
        return depth
    except ValueError:
        raise unf_exception.UnfoldError(
            f"Invalid max_depth config: '{value}'. Must be a positive integer"
        )


def get_max_depth_config() -> Optional[int]:
    value = tk.config.get("ckanext.unfold.max_depth")
    return parse_max_depth(value)


def parse_max_nested_count(value: Optional[str]) -> Optional[int]:
    if not value:
        return None  # Default: no limit

    try:
        count = int(value)
        if count < 1:
            raise unf_exception.UnfoldError(
                f"Max nested count must be >= 1, got: {count}"
            )
        return count
    except ValueError:
        raise unf_exception.UnfoldError(
            f"Invalid max_nested_count config: '{value}'. Must be a positive integer"
        )


def get_max_nested_count_config() -> Optional[int]:
    value = tk.config.get("ckanext.unfold.max_nested_count")
    return parse_max_nested_count(value)


def parse_max_count(value: Optional[str]) -> Optional[int]:
    if not value:
        return None  # Default: no limit

    try:
        count = int(value)
        if count < 1:
            raise unf_exception.UnfoldError(f"Max count must be >= 1, got: {count}")
        return count
    except ValueError:
        raise unf_exception.UnfoldError(
            f"Invalid max_count config: '{value}'. Must be a positive integer"
        )


def get_max_count_config() -> Optional[int]:
    value = tk.config.get("ckanext.unfold.max_count")
    return parse_max_count(value)


def get_max_size_config() -> Optional[int]:
    value = tk.config.get("ckanext.unfold.max_size")
    return parse_size_config(value)


def parse_formats(value: Optional[str], supported_formats: list[str]) -> list[str]:
    if not value or not value.strip():
        return list(supported_formats)  # Default: all supported formats

    formats = [fmt.strip().lower() for fmt in value.split() if fmt.strip()]

    unsupported = [fmt for fmt in formats if fmt not in supported_formats]
    if unsupported:
        log.warning(
            f"Unsupported formats in config: {unsupported}. "
            f"Supported formats: {supported_formats}"
        )
    return [fmt for fmt in formats if fmt in supported_formats]


def get_formats_config() -> list[str]:
    value = tk.config.get("ckanext.unfold.formats")
    return parse_formats(value, list(unf_adapters.ADAPTERS.keys()))
