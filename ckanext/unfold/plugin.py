from __future__ import annotations

from typing import Any

import ckan.plugins as plugins
import ckan.plugins.toolkit as tk
from ckan.common import CKANConfig
from ckan.types import Context, DataDict

import ckanext.unfold.adapters as unf_adapters
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.logic.schema import get_preview_schema


@tk.blanket.actions
@tk.blanket.validators
class UnfoldPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IResourceView, inherit=True)
    plugins.implements(plugins.IResourceController, inherit=True)

    # IConfigurer

    def update_config(self, config_: CKANConfig):
        tk.add_template_directory(config_, "templates")
        tk.add_public_directory(config_, "public")
        tk.add_resource("assets", "unfold")

    # IResourceView

    def info(self) -> dict[str, Any]:
        return {
            "name": "unfold_view",
            "title": tk._("Unfold"),
            "icon": "archive",
            "schema": get_preview_schema(),
            "iframed": False,
            "always_available": True,
            "default_title": tk._("Unfold"),
        }

    def can_view(self, data_dict: DataDict) -> bool:
        return data_dict["resource"].get("format", "").lower() in unf_adapters.ADAPTERS

    def view_template(self, context: Context, data_dict: DataDict) -> str:
        return "unfold_preview.html"

    def form_template(self, context: Context, data_dict: DataDict) -> str:
        return "unfold_form.html"

    # IResourceController

    def before_resource_update(
        self, context: Context, current: dict[str, Any], resource: dict[str, Any]
    ) -> None:
        if resource.get("url_type") == "upload" and not resource.get("upload"):
            return

        if resource.get("url_type") == "url" and current["url"] == resource["url"]:
            return

        unf_utils.delete_archive_structure(resource["id"])

    def before_resource_delete(
        self,
        context: Context,
        resource: dict[str, Any],
        resources: list[dict[str, Any]],
    ) -> None:
        unf_utils.delete_archive_structure(resource["id"])
