from ckan import types
from ckan.logic.schema import validator_args


@validator_args
def get_preview_schema(
    ignore_empty: types.Validator,
    unicode_safe: types.Validator,
    url_validator: types.Validator,
) -> types.Schema:
    return {
        "file_url": [ignore_empty, unicode_safe, url_validator],
        "archive_pass": [ignore_empty, unicode_safe],
    }


@validator_args
def get_archive_structure(
    not_empty: types.Validator,
    unicode_safe: types.Validator,
    resource_id_exists: types.Validator,
    resource_view_id_exists: types.Validator,
    ignore_empty: types.Validator,
) -> types.Schema:
    return {
        "id": [not_empty, unicode_safe, resource_id_exists],
        "view_id": [not_empty, unicode_safe, resource_view_id_exists],
        "parent_id": [ignore_empty, unicode_safe],
    }
