from __future__ import annotations

from typing import Any

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan import types
from ckan.common import CKANConfig

import ckanext.unfold.config as unf_config
import ckanext.unfold.jobs as unf_jobs
import ckanext.unfold.utils as unf_utils
from ckanext.unfold.adapters import adapter_registry
from ckanext.unfold.logic.action import VIEW_TYPE
from ckanext.unfold.logic.schema import get_preview_schema


@tk.blanket.actions
@tk.blanket.auth_functions
@tk.blanket.validators
@tk.blanket.config_declarations
@tk.blanket.cli
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

    # IConfigurer
    def update_config(self, config_: CKANConfig):
        tk.add_template_directory(config_, "templates")
        tk.add_resource("assets", "unfold")

    # IResourceView
    def info(self) -> dict[str, Any]:
        return {
            "name": VIEW_TYPE,
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

    def setup_template_variables(
        self, context: types.Context, data_dict: types.DataDict
    ) -> dict[str, Any]:
        return {
            "show_context_menu_default": unf_config.get_context_menu_default(),
            "page_size": unf_config.get_page_size(),
            "can_rebuild": self._can_rebuild(context, data_dict["resource"]),
        }

    @staticmethod
    def _can_rebuild(context: types.Context, resource: dict[str, Any]) -> bool:
        try:
            tk.check_access("rebuild_archive_index", context, {"id": resource["id"]})
        except (tk.NotAuthorized, tk.ObjectNotFound):
            return False

        return True

    # IResourceController

    def after_resource_update(
        self, context: types.Context, resource: dict[str, Any]
    ) -> None:
        """Re-warm the cache for every Unfold view of this resource."""
        views = tk.get_action("resource_view_list")(
            {"ignore_auth": True}, {"id": resource["id"]}
        )

        for view in views:
            if view.get("view_type") != VIEW_TYPE:
                continue

            unf_jobs.enqueue_cache_warm(resource, view)

    def before_resource_delete(
        self,
        context: types.Context,
        resource: dict[str, Any],
        resources: list[dict[str, Any]],
    ) -> None:
        unf_utils.UnfoldCacheManager.delete(resource["id"])
