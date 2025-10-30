from typing import Any

from ckan import types
from ckan.logic import validate
from ckan.plugins import toolkit as tk

import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception
import ckanext.unfold.logic.schema as unf_schema
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils


@tk.side_effect_free
@validate(unf_schema.get_archive_structure)
def get_archive_structure(
    context: types.Context, data_dict: types.Dict[str, str]
) -> dict[str, str] | list[dict[str, Any]]:
    """Return archive tree nodes."""
    resource = tk.get_action("resource_show")(context, {"id": data_dict["id"]})
    resource_view = tk.get_action("resource_view_show")(
        context, {"id": data_dict["view_id"]}
    )

    try:
        nodes = unf_utils.get_archive_tree(resource, resource_view)
    except unf_exception.UnfoldError as e:
        return {"error": str(e)}

    close_folders = len(nodes) > unf_config.get_expand_nodes_threshold()
    return [serialize_node(n, close_folders) for n in nodes]


def serialize_node(node: unf_types.Node, close_folders: bool) -> dict[str, Any]:
    data = node.model_dump()

    size = node.data.get("size", "")
    modified_at = node.data.get("modified_at", "")

    if size or modified_at:
        data["text"] += "<span class='unfold-node-metadata'>"

        if size:
            data["text"] += f' <span class="unfold-node-size">{size}</span>'

        if modified_at:
            data["text"] += (
                f' <span class="unfold-node-modified-at">{modified_at}</span>'
            )

        data["text"] += "</span>"

    if node.data.get("type") == "folder":
        data["state"] = {"opened": not close_folders}  # Optionally: don't start opened

    return data
