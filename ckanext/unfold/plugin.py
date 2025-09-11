from __future__ import annotations

from typing import Any

import ckan.plugins as plugins
import ckan.plugins.toolkit as tk
from ckan.common import CKANConfig
from ckan.types import Context, DataDict

import ckanext.unfold.adapters as unf_adapters
import ckanext.unfold.config as unf_config
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.logic.schema import get_preview_schema


@tk.blanket.actions
@tk.blanket.validators
class UnfoldPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IResourceView, inherit=True)
    plugins.implements(plugins.IResourceController, inherit=True)

    # IConfigDeclaration
    def declare_config_options(self, declaration, key):
        declaration.declare(key.ckanext.unfold.max_size, "50MB").set_description(
            "Maximum size of archives to process (e.g., 50MB, 1GB)"
        )
        declaration.declare(key.ckanext.unfold.max_depth, 4).set_description(
            "Maximum depth of archive structure to display"
        )
        declaration.declare(key.ckanext.unfold.max_nested_count, 20).set_description(
            "Maximum number of items to show per folder"
        )
        declaration.declare(key.ckanext.unfold.max_count, 100).set_description(
            "Maximum total number of items to display from archive"
        )
        declaration.declare(key.ckanext.unfold.formats, "zip tar 7z rar").set_description(
            "Supported archive formats (space-separated list)"
        )

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
        resource_format = data_dict["resource"].get("format", "").lower()
        allowed_formats = unf_config.get_formats_config()
        return resource_format in allowed_formats

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
