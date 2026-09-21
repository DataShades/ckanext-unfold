"""Folder-by-folder index of an archive's node list.

Adapters produce a flat list of :class:`Node` objects. For small archives
that list is sent to the browser in one go; for large ones the browser
would freeze building the DOM, so the tree is indexed by parent and served
one folder per request (see ``logic/action.py``). This module builds that
index and answers the two questions the UI asks: "children of this folder"
and "which folders must be opened to show matches for this query".

No CKAN dependency, so it is unit-testable on its own.
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import islice

from ckanext.unfold.types import Node

ROOT = "#"
FOLDER_ICON = "fa fa-folder"
DEFAULT_SEARCH_LIMIT = 200


@dataclass
class SearchResult:
    #: ids of the folders that must be opened, parents before children
    ids: list[str]
    #: number of matching entries in the whole archive
    matches: int
    #: whether ``ids`` and ``results`` only cover the first ``limit`` matches
    truncated: bool
    #: the matching nodes themselves (first ``limit``), for a flat result list
    results: list[Node] = field(default_factory=list)


def ancestors(node_id: str) -> list[str]:
    """Folder ids leading to ``node_id``, outermost first."""
    parts = [p for p in node_id.split("/") if p]

    return ["/".join(parts[:i]) for i in range(1, len(parts))]


def search_paths(paths: list[str], query: str, limit: int) -> tuple[list[str], int]:
    """Case-insensitive substring search over node ids.

    Returns the first ``limit`` matching ids and the total number of matches.
    """
    query = query.lower()
    matched: list[str] = []
    matches = 0

    for path in paths:
        if query not in path.lower():
            continue

        matches += 1

        if matches <= limit:
            matched.append(path)

    return matched, matches


def build_search_result(
    matched: list[str], matches: int, limit: int, nodes: list[Node]
) -> SearchResult:
    """Assemble a result: ancestor folders to open, plus the matched nodes."""
    ids: list[str] = []
    seen: set[str] = set()

    for path in matched:
        for folder in ancestors(path):
            if folder not in seen:
                seen.add(folder)
                ids.append(folder)

    return SearchResult(
        ids=ids, matches=matches, truncated=matches > limit, results=nodes
    )


def encode_folder(nodes: list[Node]) -> str:
    """Serialize one folder's children for the cache: one JSON object per line.

    Only what cannot be derived is stored: the parent is the key the folder
    is stored under, ``text`` is the last part of the id for every built-in
    adapter, and ``state`` is never sent to the browser as it is (see
    ``_serialize_node``). ``None`` attributes and a false ``children`` are left
    out too, so a plain file costs about half of what ``dataclasses.asdict`` did.

    One node per line lets :func:`decode_folder` read the first page of a
    folder with tens of thousands of entries without parsing the rest. JSON
    never contains a raw newline (it is escaped), so the split is safe.
    """
    lines: list[str] = []

    for node in nodes:
        item: dict[str, object] = {"id": node.id}

        if node.text != _basename(node.id):
            item["text"] = node.text

        item["icon"] = node.icon
        item["data"] = node.data

        if node.li_attr is not None:
            item["li_attr"] = node.li_attr

        if node.a_attr is not None:
            item["a_attr"] = node.a_attr

        if node.children:
            item["children"] = True

        lines.append(json.dumps(item, separators=(",", ":")))

    return "\n".join(lines)


def decode_folder(
    raw: bytes | str, parent: str, limit: int | None = None
) -> list[Node]:
    """Inverse of :func:`encode_folder`: the first ``limit`` nodes (all if
    ``None``) of the folder stored as ``raw``, whose parent id is ``parent``.
    """
    stream = io.BytesIO(raw.encode() if isinstance(raw, str) else raw)
    nodes: list[Node] = []

    for line in islice(stream, limit):
        item = json.loads(line)
        nodes.append(
            Node(
                id=item["id"],
                text=item.get("text", _basename(item["id"])),
                icon=item["icon"],
                parent=parent,
                data=item["data"],
                li_attr=item.get("li_attr"),
                a_attr=item.get("a_attr"),
                children=item.get("children", False),
            )
        )

    return nodes


def _basename(node_id: str) -> str:
    return node_id.rsplit("/", 1)[-1]


def folder_size(raw: bytes | str) -> int:
    """Number of nodes in a folder stored by :func:`encode_folder`."""
    if not raw:
        return 0

    if isinstance(raw, str):
        return raw.count("\n") + 1

    return raw.count(b"\n") + 1


@dataclass
class ArchiveIndex:
    """In-memory index: every node grouped under its parent id."""

    total: int
    children: dict[str, list[Node]]
    paths: list[str] = field(default_factory=list)

    @classmethod
    def from_nodes(cls, nodes: list[Node]) -> ArchiveIndex:
        """Group nodes by parent, add missing folders, sort, flag folders.

        Adapters do not all emit directory entries (tar, 7z, rar and ar
        may list ``a/b/c.txt`` without ``a`` or ``a/b``). Missing ancestors
        are created here so every node has a reachable parent; duplicates
        by id are dropped, first occurrence wins.
        """
        by_id: dict[str, Node] = {}

        for node in nodes:
            if node.id not in by_id:
                by_id[node.id] = node

        for node in list(by_id.values()):
            _ensure_ancestors(node, by_id)

        children: dict[str, list[Node]] = defaultdict(list)

        for node in by_id.values():
            children[node.parent].append(node)

        for node in by_id.values():
            node.children = bool(children.get(node.id))

        for siblings in children.values():
            siblings.sort(key=_sort_key)

        return cls(
            total=len(by_id),
            children=dict(children),
            paths=list(by_id),
        )

    def children_of(self, parent: str) -> list[Node]:
        return self.children.get(parent, [])

    def children_page(self, parent: str, limit: int) -> tuple[list[Node], int]:
        """The first ``limit`` children of ``parent``, and how many it has."""
        siblings = self.children_of(parent)

        return siblings[:limit], len(siblings)

    def all_nodes(self) -> list[Node]:
        return [node for siblings in self.children.values() for node in siblings]

    def node(self, node_id: str) -> Node | None:
        if not hasattr(self, "_by_id"):
            self._by_id = {n.id: n for n in self.all_nodes()}

        return self._by_id.get(node_id)

    def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> SearchResult:
        matched, matches = search_paths(self.paths, query, limit)
        nodes = [n for n in (self.node(i) for i in matched) if n is not None]

        return build_search_result(matched, matches, limit, nodes)


def _ensure_ancestors(node: Node, by_id: dict[str, Node]) -> None:
    parent = node.parent

    while parent != ROOT and parent not in by_id:
        parts = [p for p in parent.split("/") if p]

        if not parts:
            node.parent = ROOT
            return

        folder = Node(
            id=parent,
            text=parts[-1],
            icon=FOLDER_ICON,
            parent="/".join(parts[:-1]) or ROOT,
            data={"size": "", "modified_at": ""},
        )
        by_id[parent] = folder
        parent = folder.parent


def _sort_key(node: Node) -> tuple[int, str]:
    # folders first, then case-insensitive by name
    return (0 if node.children or node.icon == FOLDER_ICON else 1, node.text.lower())
