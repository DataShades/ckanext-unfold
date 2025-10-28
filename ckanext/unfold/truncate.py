from __future__ import annotations

from collections import defaultdict

import ckanext.unfold.config as unf_config
import ckanext.unfold.types as unf_types


def truncate_nodes(
    nodes: list[unf_types.Node],
    max_depth: int | None = None,
    max_nested: int | None = None,
    max_total: int | None = None,
) -> list[unf_types.Node]:
    if not nodes:
        return []

    max_depth = max_depth or unf_config.get_max_depth()
    max_nested = max_nested or unf_config.get_max_nested_count()
    max_total = max_total or unf_config.get_max_total()

    result: list[unf_types.Node] = []
    current_total_count = 0
    depths: dict[str, int] = {}

    folder_counts: defaultdict[str, int] = defaultdict(int)
    file_counts: defaultdict[str, int] = defaultdict(int)
    hidden_nodes: set[str] = set()

    # Track which parents need truncation markers
    needs_truncation_marker: dict[str, int] = {}

    ordered_nodes = sort_nodes(nodes)

    for i, node in enumerate(ordered_nodes):
        if _is_hidden(node.id, node.parent, hidden_nodes):
            continue

        depth = _compute_depth(node, depths)
        node_type = _node_type(node)

                # Total count truncation - check first to prioritize it
        if max_total is not None and current_total_count >= max_total:
            # Count remaining visible nodes
            remaining_nodes = [
                n
                for n in ordered_nodes[i:]
                if not _is_hidden(n.id, n.parent, hidden_nodes)
            ]
            if remaining_nodes:
                needs_truncation_marker["#"] = len(remaining_nodes)
            break

        # Depth truncation
        if depth > max_depth:
            needs_truncation_marker[node.parent] = 0
            hidden_nodes.add(node.id)
            continue

        # Nested truncation for folders
        if node_type == "folder" and folder_counts[node.parent] >= max_nested:
            needs_truncation_marker[node.parent] = 0
            hidden_nodes.add(node.id)
            continue

        # Nested truncation for files
        if node_type == "file" and file_counts[node.parent] >= max_nested:
            needs_truncation_marker[node.parent] = 0
            continue

        result.append(node)
        current_total_count += 1

        if node_type == "folder":
            folder_counts[node.parent] += 1
        else:
            file_counts[node.parent] += 1

    # Add truncation markers at the end
    for parent_id, remaining in needs_truncation_marker.items():
        _add_truncation_marker(result, parent_id, remaining)

    return result


def sort_nodes(nodes: list[unf_types.Node]) -> list[unf_types.Node]:
    def sort_key(node: unf_types.Node):
        parts = node.id.strip("/").split("/")
        is_file = node.data.get("type") == "file"
        key = [(1, part) for part in parts[:-1]]
        key.append((0 if is_file else 1, parts[-1]))
        return key

    return sorted(nodes, key=sort_key)


def _is_hidden(node_id: str, parent_id: str, hidden_nodes: set[str]) -> bool:
    if node_id in hidden_nodes:
        return True
    pid = parent_id
    while pid and pid != "#":
        if pid in hidden_nodes:
            return True
        pid = pid.rsplit("/", 1)[0] if "/" in pid else "#"
    return False


def _compute_depth(node: unf_types.Node, depths: dict[str, int]) -> int:
    if node.parent == "#":
        depth = 0
    elif node.parent in depths:
        depth = depths[node.parent] + 1
    else:
        depth = node.id.strip("/").count("/")
    depths[node.id] = depth
    return depth


def _add_truncation_marker(
    result: list[unf_types.Node], parent_id: str, remaining: int = 0
) -> None:
    # Check if we already have a truncation marker for this parent
    if result and result[-1].id == f"{parent_id}/__truncated__":
        return

    # Also check if any existing truncation marker exists for this parent
    for node in result:
        if node.id == f"{parent_id}/__truncated__":
            return
    result.append(_create_truncation_node(parent_id, remaining))


def _node_type(node: unf_types.Node) -> str:
    return "folder" if node.data.get("type") == "folder" else "file"


def _create_truncation_node(parent_id: str, truncated_count: int) -> unf_types.Node:
    return unf_types.Node(
        id=f"{parent_id}/__truncated__",
        text=(
            " truncated"
            if not truncated_count
            else f"~{truncated_count} more items truncated"
        ),
        icon="fa fa-ellipsis-h",
        parent=parent_id,
        state={"opened": False},
        data={"size": "", "type": "truncation", "format": "", "modified_at": "--"},
    )
