from __future__ import annotations

from typing import Any

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan import types
from ckan.common import CKANConfig

import ckanext.unfold.utils as unf_utils
from ckanext.unfold.adapters import adapter_registry
from ckanext.unfold.logic.schema import get_preview_schema


@tk.blanket.actions
@tk.blanket.validators
@tk.blanket.config_declarations
class UnfoldPlugin(p.SingletonPlugin):
    p.implements(p.IConfigurable)
    p.implements(p.IConfigurer)
    p.implements(p.IResourceView, inherit=True)
    p.implements(p.IResourceController, inherit=True)

    # IConfigurable

    def configure(self, config_: CKANConfig):
        self._register_adapters()

    @classmethod
    def _register_adapters(cls):
        unf_utils.collect_adapters_signal.send(adapter_registry)
        # for _ in unf_utils.collect_adapters_signal.send(adapter_registry):
        #     pass

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
            "default_title": tk._("Unfold"),
        }

    def can_view(self, data_dict: types.DataDict) -> bool:
        return unf_utils.get_adapter_for_resource(data_dict["resource"]) is not None

    def view_template(self, context: types.Context, data_dict: types.DataDict) -> str:
        return "unfold_preview.html"

    def form_template(self, context: types.Context, data_dict: types.DataDict) -> str:
        return "unfold_form.html"

    # IResourceController

    def before_resource_update(
        self, context: types.Context, current: dict[str, Any], resource: dict[str, Any]
    ) -> None:
        if resource.get("url_type") == "upload" and not resource.get("upload"):
            return

        if resource.get("url_type") == "url" and current["url"] == resource["url"]:
            return

        unf_utils.UnfoldCacheManager.delete(resource["id"])

    def before_resource_delete(
        self,
        context: types.Context,
        resource: dict[str, Any],
        resources: list[dict[str, Any]],
    ) -> None:
        unf_utils.UnfoldCacheManager.delete(resource["id"])
