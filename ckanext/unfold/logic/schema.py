from ckan import types
from ckan.logic.schema import validator_args


@validator_args
def get_preview_schema(
    ignore_empty: types.Validator,
    unicode_safe: types.Validator,
    url_validator: types.Validator,
    boolean_validator: types.Validator,
) -> types.Schema:
    return {
        "file_url": [ignore_empty, unicode_safe, url_validator],
        "archive_pass": [ignore_empty, unicode_safe],
        "show_context_menu": [boolean_validator],
    }


@validator_args
def get_archive_structure(  # noqa: PLR0913
    not_empty: types.Validator,
    unicode_safe: types.Validator,
    resource_id_exists: types.Validator,
    resource_view_id_exists: types.Validator,
    url_validator: types.Validator,
    boolean_validator: types.Validator,
    ignore_empty: types.Validator,
) -> types.Schema:
    return {
        "id": [not_empty, unicode_safe, resource_id_exists],
        "view_id": [ignore_empty, unicode_safe, resource_view_id_exists],
        "url": [not_empty, unicode_safe, url_validator],
        "is_remote": [not_empty, boolean_validator],
        "format": [not_empty, unicode_safe],
    }
