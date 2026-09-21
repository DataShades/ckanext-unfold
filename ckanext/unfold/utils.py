from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import redis

import ckan.plugins.toolkit as tk
from ckan.lib.redis import connect_to_redis

import ckanext.unfold.adapters as unf_adapters
import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.formats as unf_formats
import ckanext.unfold.types as unf_types
from ckanext.unfold.index import (
    DEFAULT_SEARCH_LIMIT,
    ROOT,
    ArchiveIndex,
    SearchResult,
    build_search_result,
    decode_folder,
    encode_folder,
    folder_size,
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
    * ``c:<parent id>`` - that folder's children, one JSON object per line
      (see :func:`ckanext.unfold.index.encode_folder`)

    Serving one folder is a single ``HGET``, whatever the archive size, and
    only the requested page of it is parsed.
    ``version`` is :func:`cache_version`'s fingerprint at save time; a
    mismatch at read time means the resource or view changed since, and is
    treated as a cache miss by :func:`get_archive_index`. An entry saved
    before this field existed reads back as ``version=None``, which never
    matches a freshly computed fingerprint either, so old entries are
    naturally treated as stale rather than misread.
    """

    _PREFIX = "ckanext:unfold:index:"
    _STATUS_PREFIX = "ckanext:unfold:status:"
    _BATCH = 1000

    @classmethod
    def _ensure_conn(cls) -> redis.Redis:

        return connect_to_redis()

    @classmethod
    def _key(cls, resource_id: str) -> str:
        return f"{cls._PREFIX}{resource_id}"

    @classmethod
    def _status_key(cls, resource_id: str) -> str:
        return f"{cls._STATUS_PREFIX}{resource_id}"

    @classmethod
    def save(cls, index: ArchiveIndex, resource_id: str, version: str) -> None:
        conn = cls._ensure_conn()
        key = cls._key(resource_id)

        mapping: dict[str, str] = {
            "meta": json.dumps({"total": index.total, "version": version}),
            "paths": "\0".join(index.paths),
        }

        for parent, nodes in index.children.items():
            mapping[f"c:{parent}"] = encode_folder(nodes)

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
        many keys exist. Build statuses (see :meth:`status`) go too, without
        being counted.
        """
        conn = cls._ensure_conn()
        status_keys = list(conn.scan_iter(match=f"{cls._STATUS_PREFIX}*"))
        keys = list(conn.scan_iter(match=f"{cls._PREFIX}*"))

        if status_keys:
            conn.delete(*status_keys)

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

        return decode_folder(raw, parent) if raw else []  # type: ignore

    @classmethod
    def children_page(
        cls, resource_id: str, parent: str, limit: int
    ) -> tuple[list[unf_types.Node], int]:
        """The first ``limit`` children of ``parent`` and how many it has.

        Unlike :meth:`children` this only builds ``limit`` nodes, so a page of
        a folder with tens of thousands of entries costs the page, not the
        folder.
        """
        raw = cls._ensure_conn().hget(cls._key(resource_id), f"c:{parent}")

        if not raw:
            return [], 0

        return decode_folder(raw, parent, limit), folder_size(raw)  # type: ignore

    @classmethod
    def all_nodes(cls, resource_id: str) -> list[unf_types.Node]:
        data: dict[bytes, bytes] = cls._ensure_conn().hgetall(cls._key(resource_id))  # type: ignore
        nodes: list[unf_types.Node] = []

        for field, raw in data.items():
            if not field.startswith(b"c:"):
                continue

            nodes.extend(decode_folder(raw, field[2:].decode()))

        return nodes

    @classmethod
    def paths(cls, resource_id: str) -> list[str]:
        raw: bytes | None = cls._ensure_conn().hget(cls._key(resource_id), "paths")  # type: ignore

        return raw.decode().split("\0") if raw else []

    @classmethod
    def delete(cls, resource_id: str) -> int:
        """Delete the resource's cache entry. Returns 1 if one existed, else 0.

        Its build status goes with it, so the next view starts from scratch.
        """
        conn = cls._ensure_conn()
        conn.delete(cls._status_key(resource_id))

        return conn.delete(cls._key(resource_id))

    # Build status
    #
    # While an index is missing, one small record per resource (a plain string
    # key, apart from the index hash so that ``save`` replacing the hash cannot
    # wipe it) tracks the background job that is producing it:
    #
    #   {"version": "...", "state": "pending"}
    #   {"version": "...", "state": "failed",
    #    "error": {"code": "...", "message": "..."}}
    #
    # ``version`` is :func:`cache_version`'s fingerprint, so a record left by an
    # older state of the resource or its view is never mistaken for the current
    # one. Records expire on their own: a pending one shortly after the job
    # would have been killed (so a crashed worker cannot leave a page
    # "processing" forever), a failed one with the cache TTL.

    @classmethod
    def status(cls, resource_id: str) -> dict[str, Any] | None:
        raw = cls._ensure_conn().get(cls._status_key(resource_id))

        return json.loads(raw) if raw else None  # type: ignore

    @classmethod
    def claim_build(cls, resource_id: str, version: str, ttl: int) -> bool:
        """Mark a build of ``version`` as pending; ``False`` if one already is.

        This is what stops a crowd of first-time visitors from each enqueueing
        a job: only the caller that gets ``True`` should enqueue. A failed
        record, or one for another version, is replaced.
        """
        conn = cls._ensure_conn()
        key = cls._status_key(resource_id)
        record = json.dumps({"version": version, "state": "pending"})

        if conn.set(key, record, nx=True, ex=ttl):
            return True

        current = cls.status(resource_id)

        if current and current["version"] == version and current["state"] == "pending":
            return False

        conn.set(key, record, ex=ttl)

        return True

    @classmethod
    def release_build(cls, resource_id: str, version: str) -> None:
        """Drop the pending record of ``version``, e.g. when its job never got
        enqueued or has finished. A record of another version is left alone.
        """
        current = cls.status(resource_id)

        if current and current["version"] == version:
            cls._ensure_conn().delete(cls._status_key(resource_id))

    @classmethod
    def fail_build(
        cls, resource_id: str, version: str, code: str, message: str
    ) -> None:
        record = json.dumps(
            {
                "version": version,
                "state": "failed",
                "error": {"code": code, "message": message},
            }
        )
        cls._ensure_conn().set(
            cls._status_key(resource_id), record, ex=unf_config.get_cache_ttl()
        )


class CachedIndex:
    """Same interface as ``ArchiveIndex``, reading from Redis on demand."""

    def __init__(self, resource_id: str) -> None:
        self.resource_id = resource_id
        self.total = UnfoldCacheManager.total(resource_id)

    def children_of(self, parent: str) -> list[unf_types.Node]:
        return UnfoldCacheManager.children(self.resource_id, parent)

    def children_page(
        self, parent: str, limit: int
    ) -> tuple[list[unf_types.Node], int]:
        return UnfoldCacheManager.children_page(self.resource_id, parent, limit)

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


def is_index_cached(resource: dict[str, Any], resource_view: dict[str, Any]) -> bool:
    """Whether Redis holds a current index for this resource and view."""
    return unf_config.is_cache_enabled() and UnfoldCacheManager.version(
        resource["id"]
    ) == cache_version(resource, resource_view)


def get_cached_index(
    resource: dict[str, Any], resource_view: dict[str, Any]
) -> CachedIndex | None:
    """The archive's index from Redis, or ``None`` if it is not (validly) there.

    Never reads the archive itself, so it is safe on the request path.
    """
    if not unf_config.is_cache_enabled():
        return None

    cached_version = UnfoldCacheManager.version(resource["id"])

    if cached_version == cache_version(resource, resource_view):
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

    return None


def get_archive_index(
    resource: dict[str, Any], resource_view: dict[str, Any]
) -> ArchiveIndex | CachedIndex:
    """Return the archive's folder index, building and caching it if needed.

    Building fetches and parses the archive right here, which can take a
    minute; requests should go through :func:`ckanext.unfold.jobs.get_index`
    instead, and leave that to a background job when one can do it.
    """
    cached = get_cached_index(resource, resource_view)

    if cached is not None:
        return cached

    cache_enabled = unf_config.is_cache_enabled()
    version = cache_version(resource, resource_view)
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
        res_format = (resource.get("format") or "").lower()
        raise unf_exception.UnfoldError(
            f"No adapter for `{res_format}` archives",
            code=unf_exception.UNSUPPORTED_FORMAT,
        )

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

    Falls through to the default registry (``adapter_registry``) if every
    result is ``None`` (including no subscribers at all). The registry key
    comes from ``resource["format"]`` and the file extension of
    ``resource["url"]``, see :func:`ckanext.unfold.formats.resolve`.
    """
    for _, adapter in get_adapter_for_resource_signal.send(resource):
        if adapter is None:
            continue

        if adapter is NO_PREVIEW:
            return None

        if adapter is False:
            break

        return adapter

    registry = unf_adapters.adapter_registry
    key = unf_formats.resolve(resource.get("format"), resource.get("url"), registry)

    return registry[key] if key else None
