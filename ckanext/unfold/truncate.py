from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils

log = logging.getLogger(__name__)

def create_truncation_node(
    parent_id: str, truncated_count: int
) -> unf_types.Node:
    return unf_types.Node(
        id=f"{parent_id}/__truncated__",
        text=" truncated" if not truncated_count else f" ({truncated_count} more items truncated)",
        icon="fa fa-ellipsis-h",
        parent=parent_id,
        state={"opened": False},
        data={
            "size": "",
            "type": "truncation",
            "format": "",
            "modified_at": "--",
        },
    )


def check_size_limit(archive_size: Optional[int], max_size: Optional[int]) -> bool:
    if max_size is None or archive_size is None:
        return True

    if archive_size > max_size:
        log.debug(
            f"Size limit exceeded: {unf_utils.printable_file_size(archive_size)} > {unf_utils.printable_file_size(max_size)}"
        )
        return False

    return True


def sort_nodes(nodes: list[unf_types.Node]) -> list[unf_types.Node]:
    def key(node: unf_types.Node) -> list[tuple[int, str]]:
        parts = node.id.strip("/").split("/")
        is_file = node.data.get("type") == "file"

        # Build key: each component except last gets (1, name) → dirs
        # Last component gets (0, name) if file, (1, name) if dir
        out = [(1, part) for part in parts[:-1]]
        out.append((0 if is_file else 1, parts[-1]))
        return out

    return sorted(nodes, key=key)

def _node_type(node) -> str:
    return "folder" if (getattr(node, "data", None) and node.data.get("type") == "folder") else "file"


def _compute_depth(node, depths: dict[str, int]) -> int:
    if node.parent == "#":
        d = 0
    elif node.parent in depths:
        d = depths[node.parent] + 1
    else:
        d = node.id.strip("/").count("/")
    depths[node.id] = d
    return d


def _has_hidden_ancestor(node_id: str, parent_id: str, hidden_prefixes: set[str]) -> bool:
    if node_id in hidden_prefixes:
        return True
    pid = parent_id
    while pid and pid != "#":
        if pid in hidden_prefixes:
            return True
        pid = pid.rsplit("/", 1)[0] if "/" in pid else "#"
    return False


def _add_trunc_marker_once(result, parent_id: str, remaining: int = 0):
    if f"{parent_id}/__truncated__" != result[-1].id:
        result.append(create_truncation_node(parent_id, remaining))

def apply_all_truncations(
    nodes: list["unf_types.Node"],
    max_depth: Optional[int] = None,
    max_nested_count: Optional[int] = None,
    max_count: Optional[int] = None,
) -> list["unf_types.Node"]:

    if not nodes:
        return []

    has_depth_limit = max_depth is not None and max_depth >= 0
    has_nested_limit = max_nested_count is not None and max_nested_count > 0
    has_count_limit = max_count is not None and max_count > 0

    if not (has_depth_limit or has_nested_limit or has_count_limit):
        return list(nodes)

    result: list["unf_types.Node"] = []
    real_count = 0  # count only real nodes (not placeholders)
    depths: dict[str, int] = {}

    parent_file_counts: defaultdict[str, int] = defaultdict(int)
    parent_folder_counts: defaultdict[str, int] = defaultdict(int)
    hidden_prefixes: set[str] = set()

    ordered = sort_nodes(nodes)

    for i, node in enumerate(ordered):
        # Skip if hidden by an ancestor
        if _has_hidden_ancestor(node.id, node.parent, hidden_prefixes):
            continue

        depth = _compute_depth(node, depths)

        # Depth truncation
        if has_depth_limit and depth > max_depth:
            _add_trunc_marker_once(result, node.parent)
            log.debug(f"Depth truncation at depth {depth} under parent '{node.parent}' (max_depth: {max_depth})")
            hidden_prefixes.add(node.id)  # hide subtree
            continue

        # Nested count truncation (files and folders counted separately)
        if has_nested_limit:
            ntype = _node_type(node)
            if ntype == "folder":
                if parent_folder_counts[node.parent] >= max_nested_count:
                    _add_trunc_marker_once(result, node.parent)
                    log.debug(f"Nested FOLDER count truncation under '{node.parent}' (limit: {max_nested_count})")
                    hidden_prefixes.add(node.id)  # hide subtree
                    continue
            else:
                if parent_file_counts[node.parent] >= max_nested_count:
                    _add_trunc_marker_once(result, node.parent)
                    log.debug(f"Nested FILE count truncation under '{node.parent}' (limit: {max_nested_count})")
                    continue  # files have no subtree

        # Total count truncation (only counts real nodes)
        if has_count_limit and real_count >= max_count - 1:
            # Count remaining *visible* nodes
            remaining_nodes = [
                n for n in ordered[i:] if not _has_hidden_ancestor(n.id, n.parent, hidden_prefixes)
            ]
            remaining = len(remaining_nodes)
            if remaining > 0:
                file_count = sum(1 for n in remaining_nodes if _node_type(n) == "file")
                folder_count = remaining - file_count
                ntype = "folder" if folder_count >= file_count else "file"
                result.append(create_truncation_node("#", remaining))
                log.debug(f"Total count truncation: {remaining} items truncated (limit: {max_count})")
            break

        # Accept node + bump counters
        result.append(node)
        real_count += 1
        if _node_type(node) == "folder":
            parent_folder_counts[node.parent] += 1
        else:
            parent_file_counts[node.parent] += 1

    return result
