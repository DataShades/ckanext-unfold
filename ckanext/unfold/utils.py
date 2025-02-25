from __future__ import annotations

import json
import logging
import math
import pathlib
from typing import Any, Callable

import ckan.lib.uploader as uploader
from ckan.lib.redis import connect_to_redis

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.adapters as unf_adapters
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
    return "%s %s" % (s, size_name[i])


def save_archive_structure(nodes: list[unf_types.Node], resource_id: str) -> None:
    """Save an archive structure to redis to"""
    conn = connect_to_redis()
    conn.set(
        f"ckanext:unfold:tree:{resource_id}",
        json.dumps([n.model_dump() for n in nodes]),
    )
    conn.close()


def get_archive_structure(resource_id: str) -> list[unf_types.Node] | None:
    """Retrieve an archive structure from redis"""
    conn = connect_to_redis()
    data = conn.get(f"ckanext:unfold:tree:{resource_id}")
    conn.close()

    return json.loads(data) if data else None  # type: ignore


def delete_archive_structure(resource_id: str) -> None:
    """Delete an archive structure from redis. Called on resource delete/update"""
    conn = connect_to_redis()
    conn.delete(f"ckanext:unfold:tree:{resource_id}")
    conn.close()


def get_archive_tree(
    resource: dict[str, Any], resource_view: dict[str, Any]
) -> list[unf_types.Node]:
    remote = False

    if resource.get("url_type") == "upload":
        upload = uploader.get_resource_uploader(resource)
        filepath = upload.get_path(resource["id"])
    else:
        if not resource.get("url"):
            return []

        filepath = resource["url"]
        remote = True

    if tree := get_archive_structure(resource["id"]):
        return tree

    adapter = get_adapter_for_format(resource["format"].lower())
    tree = adapter(filepath, resource_view, remote=remote)
    save_archive_structure(tree, resource["id"])

    return tree


def get_adapter_for_format(res_format: str) -> Callable[..., list[unf_types.Node]]:
    if res_format not in unf_adapters.ADAPTERS:
        raise unf_exception.UnfoldError(f"No adapter for `{res_format}` archives")

    return unf_adapters.ADAPTERS[res_format]
