from ckan import types
from ckan.logic import validate
from ckan.plugins import toolkit as tk

import ckanext.unfold.exception as unf_exception
import ckanext.unfold.logic.schema as unf_schema
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils


@tk.side_effect_free
@validate(unf_schema.get_archive_structure)
def get_archive_structure(
    context: types.Context, data_dict: types.Dict[str, str]
) -> dict[str, str] | list[dict[str, str]]:
    resource = tk.get_action("resource_show")(context, {"id": data_dict["id"]})
    resource_view = tk.get_action("resource_view_show")(
        context, {"id": data_dict["view_id"]}
    )

    try:
        return [
            n.model_dump() if isinstance(n, unf_types.Node) else n
            for n in unf_utils.get_archive_tree(resource, resource_view)
        ]
    except unf_exception.UnfoldError as e:
        return {"error": str(e)}
