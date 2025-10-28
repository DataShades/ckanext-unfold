import logging

import ckan.plugins.toolkit as tk
from ckan import model, types

log = logging.getLogger(__name__)


def resource_view_id_exists(resource_view_id: str, context: types.Context) -> str:
    if not model.Session.query(model.ResourceView).get(resource_view_id):
        raise tk.Invalid("Resource view not found.")

    return resource_view_id
