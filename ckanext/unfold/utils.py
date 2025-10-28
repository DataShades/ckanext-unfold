from __future__ import annotations

import json
import logging
import math
import pathlib
from collections.abc import Callable
from typing import Any

from ckan.lib.redis import connect_to_redis
from ckan.lib.uploader import get_resource_uploader

import ckanext.unfold.adapters as unf_adapters
import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.truncate as unf_truncate
import ckanext.unfold.types as unf_types

DEFAULT_DATE_FORMAT = "%d/%m/%Y - %H:%M"
DEFAULT_TIMEOUT = 60  # seconds
log = logging.getLogger(__name__)


def get_icon_by_format(fmt: str) -> str:
    default_icon = "fa fa-file"
    fmt = fmt.lstrip(".")

    icons = {
        ("csv",): "fa fa-file-csv",
        ("txt", "tsv", "ini", "nfo", "log"): "fa fa-file-text",
        ("xls", "xlsx"): "fa fa-file-excel",
        ("doc", "docx"): "fa fa-file-word",
        ("ppt", "pptx", "pptm"): "fa fa-file-powerpoint",
        (
            "ai",
            "gif",
            "ico",
            "tif",
            "tiff",
            "webp",
            "png",
            "jpeg",
            "jpg",
            "svg",
            "bmp",
            "psd",
        ): "fa fa-file-image",
        (
            "7z",
            "rar",
            "zip",
            "zipx",
            "gzip",
            "tar.gz",
            "tar",
            "deb",
            "cbr",
            "pkg",
            "apk",
        ): "fa fa-file-archive",
        ("pdf",): "fa fa-file-pdf",
        (
            "json",
            "xhtml",
            "py",
            "css",
            "rs",
            "html",
            "php",
            "sql",
            "java",
            "class",
        ): "fa fa-file-code",
        ("xml", "dtd"): "fa fa-file-contract",
        ("mp3", "wav", "wma", "aac", "flac", "mpa", "ogg"): "fa fa-file-audio",
        ("fnt", "fon", "otf", "ttf"): "fa fa-font",
        ("pub", "pem"): "fa fa-file-shield",
    }

    for formats, icon in icons.items():
        for _format in formats:
            if _format == fmt:
                return icon

    return default_icon


def name_from_path(path: str | None) -> str:
    return path.rstrip("/").split("/")[-1] if path else ""


def get_format_from_name(name: str) -> str:
    return pathlib.Path(name).suffix


def printable_file_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 bytes"
    size_name = ("bytes", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(float(size_bytes) / p, 1)
    return f"{s} {size_name[i]}"


def save_archive_structure(nodes: list[unf_types.Node], resource_id: str) -> None:
    """Save an archive structure to redis to."""
    conn = connect_to_redis()
    conn.set(
        f"ckanext:unfold:tree:{resource_id}",
        json.dumps([n.model_dump() for n in nodes]),
    )
    conn.close()


def get_archive_structure(resource_id: str) -> list[unf_types.Node] | None:
    """Retrieve an archive structure from redis."""
    conn = connect_to_redis()
    data = conn.get(f"ckanext:unfold:tree:{resource_id}")
    conn.close()

    return json.loads(data) if data else None  # type: ignore


def delete_archive_structure(resource_id: str) -> None:
    """Delete an archive structure from redis.

    Called on resource delete/update
    """
    conn = connect_to_redis()
    conn.delete(f"ckanext:unfold:tree:{resource_id}")
    conn.close()


def get_archive_tree(
    resource: dict[str, Any], resource_view: dict[str, Any]
) -> list[unf_types.Node]:
    remote = False

    if resource.get("url_type") == "upload":
        upload = get_resource_uploader(resource)
        filepath = upload.get_path(resource["id"])
    else:
        if not resource.get("url"):
            return []

        filepath = resource["url"]
        remote = True

    # Check size limit before processing
    archive_size = resource.get("size")
    if archive_size and isinstance(archive_size, str):
        try:
            archive_size = int(archive_size)
        except (ValueError, TypeError):
            archive_size = None

    max_size = unf_config.get_max_size()

    if not check_size_limit(archive_size, max_size):
        file_size = printable_file_size(archive_size) if archive_size else "unknown"
        max_size = printable_file_size(max_size)
        log.warning(
            "Skipping archive processing: size %s "
            "exceeds maximum allowed size of %s "
            "for resource %s",
            file_size,
            max_size,
            resource.get("id", "unknown"),
        )
        return []

    cache_enabled = unf_config.is_cache_enabled()
    cached_tree = get_archive_structure(resource["id"])

    if cache_enabled and cached_tree:
        return cached_tree

    adapter = get_adapter_for_format(resource["format"].lower())
    tree = adapter(filepath, resource_view, remote=remote)

    # Apply truncation limits before saving
    truncated_tree = unf_truncate.truncate_nodes(tree)

    if cache_enabled:
        save_archive_structure(truncated_tree, resource["id"])

    return truncated_tree


def get_adapter_for_format(res_format: str) -> Callable[..., list[unf_types.Node]]:
    if res_format not in unf_adapters.ADAPTERS:
        raise unf_exception.UnfoldError(f"No adapter for `{res_format}` archives")

    return unf_adapters.ADAPTERS[res_format]


def check_size_limit(archive_size: int | None, max_size: int | None) -> bool:
    if max_size is None or archive_size is None:
        return True

    return archive_size < max_size
