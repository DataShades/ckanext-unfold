from ckan import types
from ckan.logic.schema import validator_args


@validator_args
def get_preview_schema(
    ignore_empty: types.Validator,
    ignore_missing: types.Validator,
    unicode_safe: types.Validator,
    boolean_validator: types.Validator,
) -> types.Schema:
    return {
        "archive_pass": [ignore_empty, unicode_safe],
        "show_context_menu": [ignore_missing, boolean_validator],
    }


@validator_args
def get_archive_structure(
    not_empty: types.Validator,
    unicode_safe: types.Validator,
    resource_id_exists: types.Validator,
    resource_view_id_exists: types.Validator,
    ignore_empty: types.Validator,
    int_validator: types.Validator,
) -> types.Schema:
    return {
        "id": [not_empty, unicode_safe, resource_id_exists],
        "view_id": [ignore_empty, unicode_safe, resource_view_id_exists],
        "parent": [ignore_empty, unicode_safe],
        "limit": [ignore_empty, int_validator],
    }


@validator_args
def search_archive_structure(
    not_empty: types.Validator,
    unicode_safe: types.Validator,
    resource_id_exists: types.Validator,
    resource_view_id_exists: types.Validator,
    ignore_empty: types.Validator,
    int_validator: types.Validator,
) -> types.Schema:
    return {
        "id": [not_empty, unicode_safe, resource_id_exists],
        "view_id": [ignore_empty, unicode_safe, resource_view_id_exists],
        "q": [not_empty, unicode_safe],
        "limit": [ignore_empty, int_validator],
    }


@validator_args
def get_archive_status(
    not_empty: types.Validator,
    unicode_safe: types.Validator,
    resource_id_exists: types.Validator,
    resource_view_id_exists: types.Validator,
    ignore_empty: types.Validator,
) -> types.Schema:
    return {
        "id": [not_empty, unicode_safe, resource_id_exists],
        "view_id": [ignore_empty, unicode_safe, resource_view_id_exists],
    }


@validator_args
def rebuild_archive_index(
    not_empty: types.Validator,
    unicode_safe: types.Validator,
    resource_id_exists: types.Validator,
    resource_view_id_exists: types.Validator,
    ignore_empty: types.Validator,
) -> types.Schema:
    return {
        "id": [not_empty, unicode_safe, resource_id_exists],
        "view_id": [ignore_empty, unicode_safe, resource_view_id_exists],
    }
