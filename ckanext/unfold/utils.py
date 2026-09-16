from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict
from typing import Any

import redis

import ckan.plugins.toolkit as tk
from ckan.lib.redis import connect_to_redis

import ckanext.unfold.adapters as unf_adapters
import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.types as unf_types
from ckanext.unfold.index import (
    DEFAULT_SEARCH_LIMIT,
    ROOT,
    ArchiveIndex,
    SearchResult,
    build_search_result,
    search_paths,
)

log = logging.getLogger(__name__)


collect_adapters_signal = tk.signals.ckanext.signal(
    "unfold:register_format_adapters",
    "Collect adapters from subscribers",
)
get_adapter_for_resource_signal = tk.signals.ckanext.signal(
    "unfold:get_adapter_for_resource",
    "Get adapter for a given resource",
)


class NoPreview:
    """Sentinel a ``get_adapter_for_resource_signal`` subscriber returns to
    mean this resource must never be previewed - see
    :func:`get_adapter_for_resource` for the full protocol.

    Unlike ``False``, which only overrides any later result and still lets
    the default format registry decide, returning this skips the registry
    too, so ``can_view`` reports ``False`` for the resource regardless of
    what adapter its format would otherwise get.
    """

    def __repr__(self) -> str:
        return "NO_PREVIEW"



NO_PREVIEW = NoPreview()


def cache_version(resource: dict[str, Any], resource_view: dict[str, Any]) -> str:
    """Fingerprint of all values that affect the tree built for this resource.

    Compared against the current resource state when reading the cached index to
    ensure the cache is invalidated whenever any relevant value changes.

    ``metadata_modified`` is used instead of ``last_modified`` because it changes
    for any resource update, including changes to ``url`` and ``format``, while
    ``last_modified`` only changes when a new file is uploaded.

    ``archive_pass`` is included because the password affects the archive contents
    available to the server. Different passwords must therefore produce separate
    cached indexes.
    """
    raw = "\0".join(
        [
            resource.get("url") or "",
            resource.get("format") or "",
            str(resource.get("metadata_modified") or ""),
            resource_view.get("archive_pass") or "",
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class UnfoldCacheManager:
    """Archive indexes in Redis, one hash per resource.

    Hash layout (key ``ckanext:unfold:index:<resource_id>``):

    * ``meta``  - JSON ``{"total": n, "version": "..."}``
    * ``paths`` - all node ids joined with NUL, for search
    * ``c:<parent id>`` - JSON list of that folder's children

    Serving one folder is a single ``HGET``, whatever the archive size.
    ``version`` is :func:`cache_version`'s fingerprint at save time; a
    mismatch at read time means the resource or view changed since, and is
    treated as a cache miss by :func:`get_archive_index`. An entry saved
    before this field existed reads back as ``version=None``, which never
    matches a freshly computed fingerprint either, so old entries are
    naturally treated as stale rather than misread.
    """

    _conn: redis.Redis | None = None
    _PREFIX = "ckanext:unfold:index:"
    _BATCH = 1000

    @classmethod
    def _ensure_conn(cls) -> redis.Redis:
        if cls._conn is None:
            cls._conn = connect_to_redis()

        return cls._conn

    @classmethod
    def _key(cls, resource_id: str) -> str:
        return f"{cls._PREFIX}{resource_id}"

    @classmethod
    def save(cls, index: ArchiveIndex, resource_id: str, version: str) -> None:
        conn = cls._ensure_conn()
        key = cls._key(resource_id)

        mapping: dict[str, str] = {
            "meta": json.dumps({"total": index.total, "version": version}),
            "paths": "\0".join(index.paths),
        }

        for parent, nodes in index.children.items():
            mapping[f"c:{parent}"] = json.dumps([asdict(n) for n in nodes])

        pipe = conn.pipeline()
        pipe.delete(key)

        items = list(mapping.items())
        for start in range(0, len(items), cls._BATCH):
            pipe.hset(key, mapping=dict(items[start : start + cls._BATCH]))

        pipe.expire(key, unf_config.get_cache_ttl())
        pipe.execute()

    @classmethod
    def exists(cls, resource_id: str) -> bool:
        return bool(cls._ensure_conn().hexists(cls._key(resource_id), "meta"))

    @classmethod
    def version(cls, resource_id: str) -> str | None:
        """The fingerprint the cached index was saved with, or ``None``.

        ``None`` covers both "nothing cached" and "cached before this field
        existed" - either way the caller should treat it as a miss.
        """
        raw = cls._ensure_conn().hget(cls._key(resource_id), "meta")

        return json.loads(raw).get("version") if raw else None  # type: ignore

    @classmethod
    def clear_all(cls) -> int:
        """Delete every resource's cached index. Returns how many were removed.

        Uses ``SCAN`` rather than ``KEYS``: safe to run against a Redis
        instance shared with the rest of CKAN without blocking it, however
        many keys exist.
        """
        conn = cls._ensure_conn()
        keys = list(conn.scan_iter(match=f"{cls._PREFIX}*"))

        if not keys:
            return 0

        return conn.delete(*keys)

    @classmethod
    def total(cls, resource_id: str) -> int:
        raw = cls._ensure_conn().hget(cls._key(resource_id), "meta")

        return json.loads(raw)["total"] if raw else 0  # type: ignore

    @classmethod
    def children(cls, resource_id: str, parent: str) -> list[unf_types.Node]:
        raw = cls._ensure_conn().hget(cls._key(resource_id), f"c:{parent}")

        return [unf_types.Node(**n) for n in json.loads(raw)] if raw else []  # type: ignore

    @classmethod
    def all_nodes(cls, resource_id: str) -> list[unf_types.Node]:
        data: dict[bytes, bytes] = cls._ensure_conn().hgetall(cls._key(resource_id))  # type: ignore
        nodes: list[unf_types.Node] = []

        for field, raw in data.items():
            if field.startswith(b"c:"):
                nodes.extend(unf_types.Node(**n) for n in json.loads(raw))

        return nodes

    @classmethod
    def paths(cls, resource_id: str) -> list[str]:
        raw: bytes | None = cls._ensure_conn().hget(cls._key(resource_id), "paths")  # type: ignore

        return raw.decode().split("\0") if raw else []

    @classmethod
    def delete(cls, resource_id: str) -> int:
        """Delete the resource's cache entry. Returns 1 if one existed, else 0."""
        return cls._ensure_conn().delete(cls._key(resource_id))

    @classmethod
    def close(cls) -> None:
        if not cls._conn:
            return

        cls._conn.close()
        cls._conn = None


class CachedIndex:
    """Same interface as ``ArchiveIndex``, reading from Redis on demand."""

    def __init__(self, resource_id: str) -> None:
        self.resource_id = resource_id
        self.total = UnfoldCacheManager.total(resource_id)

    def children_of(self, parent: str) -> list[unf_types.Node]:
        return UnfoldCacheManager.children(self.resource_id, parent)

    def all_nodes(self) -> list[unf_types.Node]:
        return UnfoldCacheManager.all_nodes(self.resource_id)

    def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> SearchResult:
        paths = UnfoldCacheManager.paths(self.resource_id)
        matched, matches = search_paths(paths, query, limit)

        # matched nodes live in their parents' child lists: one HGET per parent
        siblings: dict[str, dict[str, unf_types.Node]] = {}
        nodes: list[unf_types.Node] = []

        for path in matched:
            parts = [p for p in path.split("/") if p]
            parent = "/".join(parts[:-1]) or ROOT

            if parent not in siblings:
                siblings[parent] = {n.id: n for n in self.children_of(parent)}

            node = siblings[parent].get(path)

            if node is not None:
                nodes.append(node)

        return build_search_result(matched, matches, limit, nodes)


def get_archive_index(
    resource: dict[str, Any], resource_view: dict[str, Any]
) -> ArchiveIndex | CachedIndex:
    """Return the archive's folder index, building and caching it if needed."""
    cache_enabled = unf_config.is_cache_enabled()
    version = cache_version(resource, resource_view)

    if cache_enabled:
        cached_version = UnfoldCacheManager.version(resource["id"])

        if cached_version == version:
            cached = CachedIndex(resource["id"])
            log.info(
                "Resource %s: serving %s entries from the Redis index",
                resource["id"],
                cached.total,
            )
            return cached

        if cached_version is not None:
            log.info(
                "Resource %s: cached index is stale (url, format, "
                "metadata_modified or the view's password changed); rebuilding",
                resource["id"],
            )

    started = time.monotonic()
    log.info(
        "Building archive index for resource %s (%s, cache %s)",
        resource["id"],
        resource.get("url"),
        "on" if cache_enabled else "off",
    )

    nodes = get_archive_tree(resource, resource_view)
    log.info(
        "Resource %s: adapter returned %s entries in %.1fs",
        resource["id"],
        len(nodes),
        time.monotonic() - started,
    )

    index = ArchiveIndex.from_nodes(nodes)

    if cache_enabled:
        UnfoldCacheManager.save(index, resource["id"], version)

    log.info(
        "Resource %s: indexed %s entries in %.1fs total",
        resource["id"],
        index.total,
        time.monotonic() - started,
    )

    return index


def get_archive_tree(
    resource: dict[str, Any], resource_view: dict[str, Any]
) -> list[unf_types.Node]:
    """Build the flat node list for a resource with the matching adapter."""
    adapter_cls = get_adapter_for_resource(resource)

    if adapter_cls is None:
        res_format = resource["format"].lower()
        raise unf_exception.UnfoldError(f"No adapter for `{res_format}` archives")

    return _build_archive_tree(adapter_cls, resource_view, resource)


def _build_archive_tree(
    adapter_cls: type[unf_adapters.BaseAdapter],
    resource_view: dict[str, Any],
    resource: dict[str, Any],
    filepath: str | None = None,
) -> list[unf_types.Node]:
    adapter_instance = adapter_cls(resource, resource_view, filepath=filepath)
    return adapter_instance.build_archive_tree()


def get_adapter_for_resource(
    resource: dict[str, Any],
) -> type[unf_adapters.BaseAdapter] | None:
    """Return the adapter class to use for ``resource``, or ``None`` to skip preview.

    ``get_adapter_for_resource_signal.send()`` always calls every connected
    subscriber - blinker signals have no way to short-circuit that - so this
    is about which of their results wins, not about skipping a call. Results
    are considered in connection order:

    * an adapter class wins outright: no later result or the default
      registry is consulted;
    * ``None`` means this subscriber has no opinion - the next result (or,
      if none is left, the default registry) decides instead;
    * :data:`NO_PREVIEW` wins outright like an adapter class does, except it
      returns ``None``, so the resource is never previewed regardless of
      what a later subscriber or the default registry would have picked for
      its format;
    * ``False`` also stops looking at any later result, but - unlike
      :data:`NO_PREVIEW` - still falls through to the default registry
      lookup by format. It only suppresses a *later custom* adapter, not the
      built-in one for that format.

    Falls through to the default registry (``adapter_registry``) by
    ``resource["format"]`` if every result is ``None`` (including no
    subscribers at all).
    """
    res_format = resource["format"].lower()

    for _, adapter in get_adapter_for_resource_signal.send(resource):
        if adapter is None:
            continue

        if adapter is NO_PREVIEW:
            return None

        if adapter is False:
            break

        return adapter

    return unf_adapters.adapter_registry.get(res_format)
