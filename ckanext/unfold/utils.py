from __future__ import annotations

import json
import logging
import math
import pathlib
from typing import Any

import redis

import ckan.plugins.toolkit as tk
from ckan.lib.redis import connect_to_redis

import ckanext.unfold.adapters as unf_adapters
import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types

DEFAULT_DATE_FORMAT = "%d/%m/%Y - %H:%M"
REDIS_CACHE_TTL = 3600 * 24  # 24 hour
log = logging.getLogger(__name__)


collect_adapters_signal = tk.signals.ckanext.signal(
    "unfold:register_format_adapters",
    "Collect adapters from subscribers",
)
get_adapter_for_resource_signal = tk.signals.ckanext.signal(
    "unfold:get_adapter_for_resource",
    "Get adapter for a given resource",
)


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
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(float(size_bytes) / p, 1)
    return f"{s} {size_name[i]}"


class UnfoldCacheManager:
    """Singleton storage for archive structures in Redis."""

    _instance = None
    _conn: redis.Redis | None = None
    _PREFIX = "ckanext:unfold:tree:"

    @classmethod
    def _ensure_conn(cls) -> redis.Redis:
        if cls._conn is None:
            cls._conn = connect_to_redis()

        return cls._conn

    @classmethod
    def _key(cls, resource_id: str) -> str:
        return f"{cls._PREFIX}{resource_id}"

    @classmethod
    def save(cls, nodes: list[unf_types.Node], resource_id: str) -> None:
        """Save an archive structure to Redis."""
        cls._conn = cls._ensure_conn()

        data = json.dumps([n.model_dump() for n in nodes])
        cls._conn.setex(cls._key(resource_id), REDIS_CACHE_TTL, data)

    @classmethod
    def get(cls, resource_id: str) -> list[unf_types.Node]:
        """Retrieve an archive structure from Redis."""
        cls._conn = cls._ensure_conn()

        data: bytes = cls._conn.get(cls._key(resource_id))  # type: ignore

        if not data:
            return []

        raw = json.loads(data)
        return [unf_types.Node(**n) for n in raw]

    @classmethod
    def delete(cls, resource_id: str) -> None:
        """Delete an archive structure from Redis."""
        cls._conn = cls._ensure_conn()
        cls._conn.delete(cls._key(resource_id))  # type: ignore

    @classmethod
    def close(cls) -> None:
        """Close the shared Redis connection."""
        if not cls._conn:
            return

        cls._conn.close()
        cls._conn = None


def get_archive_tree(
    resource: dict[str, Any], resource_view: dict[str, Any]
) -> list[unf_types.Node]:
    cache_enabled = unf_config.is_cache_enabled()
    cached_tree = UnfoldCacheManager.get(resource["id"])

    if cache_enabled and cached_tree:
        return cached_tree

    adapter_instance = get_adapter_for_resource(resource)(resource, resource_view)

    archive_tree = adapter_instance.build_archive_tree()

    if cache_enabled:
        UnfoldCacheManager.save(archive_tree, resource["id"])

    return archive_tree


def get_adapter_for_resource(
    resource: dict[str, Any],
) -> type[unf_adapters.BaseAdapter]:
    res_format = resource["format"].lower()

    for _, adapter in get_adapter_for_resource_signal.send(resource):
        if adapter is None:
            continue

        if adapter is False:
            break

        return adapter

    if res_format not in unf_adapters.adapter_registry:
        raise unf_exception.UnfoldError(f"No adapter for `{res_format}` archives")

    return unf_adapters.adapter_registry[res_format]
