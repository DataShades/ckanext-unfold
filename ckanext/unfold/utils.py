from __future__ import annotations

import os
import json
import logging
import math
import pathlib
import mimetypes
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any

import redis

import ckan.plugins.toolkit as tk
from ckan.lib.redis import connect_to_redis
from ckan.lib.uploader import get_resource_uploader

import ckanext.unfold.adapters as unf_adapters
import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types

DEFAULT_DATE_FORMAT = "%d/%m/%Y - %H:%M"
REDIS_CACHE_TTL = 3600 * 24  # 24 hour
TEMPORARY_LINK_TTL = 300
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

        data = json.dumps([asdict(n) for n in nodes])
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
    resource: dict[str, Any],
    resource_view: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> list[unf_types.Node]:
    cache_enabled = unf_config.is_cache_enabled()
    cached_tree = UnfoldCacheManager.get(resource["id"])

    if cache_enabled and cached_tree:
        return cached_tree

    adapter_cls = get_adapter_for_resource(resource)
    if adapter_cls is None:
        res_format = resource["format"].lower()
        raise unf_exception.UnfoldError(f"No adapter for `{res_format}` archives")

    if "cloudstorage" in tk.g.plugins:
        _prepare_cloudstorage_resource(resource)

    with _prepare_file_resource(resource, context or {}) as (
        adapter_resource,
        filepath,
    ):
        adapter_instance = adapter_cls(
            adapter_resource,
            resource_view,
            filepath=filepath,
        )
        archive_tree = adapter_instance.build_archive_tree()

    if cache_enabled:
        UnfoldCacheManager.save(archive_tree, resource["id"])

    return archive_tree


@contextmanager
def _prepare_file_resource(
    resource: dict[str, Any],
    context: dict[str, Any],
) -> Iterator[tuple[dict[str, Any], str | None]]:
    """Make a ckanext-files resource readable by an archive adapter."""
    if resource.get("url_type") != "file":
        yield resource, None
        return

    file_id = resource.get("url", "").rstrip("/").rsplit("/", 1)[-1]
    if not file_id:
        raise unf_exception.UnfoldError("Unable to determine the resource file")

    try:
        files = _get_files_api()
        file_info = tk.get_action("files_file_show")(context, {"id": file_id})
        storage = files.get_storage(file_info["storage"])
        file_data = files.FileData.from_dict(file_info)
    except Exception as error:
        raise unf_exception.UnfoldError(
            f"Unable to access the resource file: {error}"
        ) from error

    try:
        temporary_url = storage.temporary_link(
            file_data,
            TEMPORARY_LINK_TTL,
        )
    except Exception:
        log.exception("Unable to create a temporary archive link")
        temporary_url = None

    if temporary_url:
        adapter_resource = resource.copy()
        adapter_resource.update(
            {
                "url": temporary_url,
                "type": "url",
                "size": file_info.get("size", resource.get("size")),
            }
        )
        yield adapter_resource, None
        return

    if not storage.supports(files.Capability.STREAM):
        raise unf_exception.UnfoldError("Resource storage does not support reading files")

    suffix = pathlib.Path(file_info.get("name", "")).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix) as target:
        try:
            for chunk in storage.stream(file_data):
                target.write(chunk)
            target.flush()
        except Exception as error:
            raise unf_exception.UnfoldError(
                f"Unable to read the resource file: {error}"
            ) from error

        yield resource, target.name


def _get_files_api() -> Any:
    """Load the storage API only when a ckanext-files resource is used."""
    try:
        from ckan.lib import files
    except ImportError:
        try:
            from ckanext.files import shared as files
        except ImportError as error:
            raise unf_exception.UnfoldError(
                "ckanext-files is required to read this resource"
            ) from error

    return files


def _prepare_cloudstorage_resource(resource: dict[str, Any]) -> None:
    uploader = get_resource_uploader(resource)

    if not any(cls.__name__ == "ResourceCloudStorage" for cls in type(uploader).__mro__):
        return

    filename = os.path.basename(resource["url"])
    content_type, _ = mimetypes.guess_type(filename)

    try:
        resource["url"] = get_resource_uploader(resource).get_url_from_filename(  # type: ignore
            resource["id"], filename, content_type=content_type
        )
    except Exception as e:
        raise unf_exception.UnfoldError(f"Error fetching remote archive: {e}") from e
    else:
        resource["type"] = "url"


def get_url_archive_tree(resource: dict[str, Any]) -> list[unf_types.Node]:
    cache_enabled = unf_config.is_cache_enabled()
    cached_tree = UnfoldCacheManager.get(resource["url"])

    if cache_enabled and cached_tree:
        return cached_tree

    adapter_cls = get_adapter_for_resource(resource)

    if adapter_cls is None:
        raise unf_exception.UnfoldError(f"No adapter for `{resource['url']}` archives")

    adapter_instance = adapter_cls(resource, {})
    archive_tree = adapter_instance.build_archive_tree()

    if cache_enabled:
        UnfoldCacheManager.save(archive_tree, resource["url"])

    return archive_tree


def get_adapter_for_resource(
    resource: dict[str, Any],
) -> type[unf_adapters.BaseAdapter] | None:
    res_format = resource["format"].lower()

    for _, adapter in get_adapter_for_resource_signal.send(resource):
        if adapter is None:
            continue

        if adapter is False:
            break

        return adapter

    return unf_adapters.adapter_registry.get(res_format)
