from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils

log = logging.getLogger(__name__)


def create_truncation_node(parent_id: str, truncated_count: int, node_type: str = "folder") -> unf_types.Node:
    return unf_types.Node(
        id=f"{parent_id}/__truncated__",
        text=f"... ({truncated_count} more items truncated)",
        icon="fa fa-folder" if node_type == "folder" else "fa fa-file",
        parent=parent_id,
        state={"opened": False},
        data={
            "size": "",
            "type": "truncation", 
            "format": "",
            "modified_at": "--",
            "truncated_count": truncated_count,
            "truncated_type": node_type
        }
    )


def check_size_limit(archive_size: Optional[int], max_size: Optional[int]) -> bool:
    if max_size is None or archive_size is None:
        return True
    
    if archive_size > max_size:
        log.debug(f"Size limit exceeded: {unf_utils.printable_file_size(archive_size)} > {unf_utils.printable_file_size(max_size)}")
        return False
    
    return True


def apply_all_truncations(
    nodes: list[unf_types.Node],
    max_depth: Optional[int] = None,
    max_nested_count: Optional[int] = None,
    max_count: Optional[int] = None
) -> list[unf_types.Node]:
        
    if not nodes:
        return []
    
    # Check if any limits are actually set (ignore None and negative values)
    has_depth_limit = max_depth is not None and max_depth >= 0
    has_nested_limit = max_nested_count is not None and max_nested_count > 0
    has_count_limit = max_count is not None and max_count > 0
    
    if not has_depth_limit and not has_nested_limit and not has_count_limit:
        return list(nodes)
    
    result = []
    depths = {}  # node_id -> depth
    parent_child_counts = defaultdict(int)  # parent_id -> count of children added
    depth_truncated_parents = set()  # parents that have depth truncation indicators
    nested_truncated_parents = set()  # parents that have nested count truncation indicators
    
    # Single pass through the ordered node list
    for i, node in enumerate(nodes):
        # Calculate depth on the fly
        if node.parent == "#":
            depth = 0
        elif node.parent in depths:
            depth = depths[node.parent] + 1
        else:
            # Fallback: calculate from path structure
            depth = len([p for p in node.id.split("/") if p]) - 1
        
        depths[node.id] = depth
        
        # Check depth limit
        if has_depth_limit and depth > max_depth:
            # Calculate parent depth properly
            if node.parent == "#":
                parent_depth = 0
            elif node.parent in depths:
                parent_depth = depths[node.parent]
            else:
                # Calculate parent depth from path structure
                parent_depth = len([p for p in node.parent.split("/") if p]) - 1
            
            # Only add truncation indicator for the immediate parent of the truncated node
            # if that parent is at max_depth and hasn't already been truncated
            if parent_depth == max_depth and node.parent not in depth_truncated_parents:
                # Determine the type of the truncated node for proper icon
                node_type = "folder" if node.data and node.data.get("type") == "folder" else "file"
                result.append(create_truncation_node(node.parent, 1, node_type))
                depth_truncated_parents.add(node.parent)
                log.debug(f"Depth truncation at depth {depth} under parent '{node.parent}' (parent depth: {parent_depth})")
            continue
        
        # Check nested count limit
        if has_nested_limit and parent_child_counts[node.parent] >= max_nested_count:
            # Add truncation indicator for this parent if not already added
            if node.parent not in nested_truncated_parents:
                node_type = "folder" if node.data and node.data.get("type") == "folder" else "file"
                result.append(create_truncation_node(node.parent, 1, node_type))
                nested_truncated_parents.add(node.parent)
                log.debug(f"Nested count truncation under parent '{node.parent}' (limit: {max_nested_count})")
            continue
        
        # Check total count limit - stop early if reached  
        if has_count_limit and len(result) >= max_count - 1:
            # Add global truncation indicator showing remaining items
            remaining = len(nodes) - i
            if remaining > 0:
                # Determine the most common type in remaining items for icon
                remaining_nodes = nodes[i:]
                file_count = sum(1 for n in remaining_nodes if n.data and n.data.get("type") == "file")
                folder_count = remaining - file_count
                # Use folder icon if more folders, or if equal counts (folders typically more important)
                node_type = "folder" if folder_count >= file_count else "file"
                result.append(create_truncation_node("#", remaining, node_type))
                log.debug(f"Total count truncation: {remaining} items truncated (limit: {max_count})")
            break
        
        # Node passes all checks - add it
        result.append(node)
        parent_child_counts[node.parent] += 1
    
    return result
