from __future__ import annotations

from typing import Any

import pytest

import ckan.plugins.toolkit as tk
from ckan import types


@pytest.fixture
def private_resource(
    user: dict[str, Any],
    organization_factory: types.TestFactory,
    package_factory: types.TestFactory,
    resource_factory: types.TestFactory,
) -> dict[str, Any]:
    """A resource of a private dataset, in an org where ``user`` is a member."""
    org = organization_factory(users=[{"name": user["name"], "capacity": "member"}])
    package = package_factory(owner_org=org["id"], private=True)

    return resource_factory(package_id=package["id"])


@pytest.mark.usefixtures("with_plugins", "clean_db")
class BaseReadPermission:
    action: str

    def test_anonymous_is_allowed_for_public_resource(self, resource: dict[str, Any]):
        """Anonymous user can browse the archive of a public resource."""
        tk.check_access(self.action, {"user": ""}, {"id": resource["id"]})

    def test_anonymous_is_not_allowed_for_private_resource(
        self, private_resource: dict[str, Any]
    ):
        """Anonymous user cannot browse the archive of a private resource."""
        with pytest.raises(tk.NotAuthorized):
            tk.check_access(self.action, {"user": ""}, {"id": private_resource["id"]})

    def test_outsider_is_not_allowed_for_private_resource(
        self, user_factory: types.TestFactory, private_resource: dict[str, Any]
    ):
        """User outside of the organization cannot browse a private resource."""
        outsider = user_factory()

        with pytest.raises(tk.NotAuthorized):
            tk.check_access(
                self.action, {"user": outsider["name"]}, {"id": private_resource["id"]}
            )

    def test_member_is_allowed_for_private_resource(
        self, user: dict[str, Any], private_resource: dict[str, Any]
    ):
        """Organization member can browse the archive of a private resource."""
        tk.check_access(
            self.action, {"user": user["name"]}, {"id": private_resource["id"]}
        )


class TestGetArchiveStructure(BaseReadPermission):
    action = "get_archive_structure"


class TestSearchArchiveStructure(BaseReadPermission):
    action = "search_archive_structure"


class TestGetArchiveStatus(BaseReadPermission):
    action = "get_archive_status"


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestRebuildArchiveIndex:
    def test_anonymous_is_not_allowed(self, resource: dict[str, Any]):
        """Anonymous user cannot rebuild an archive index."""
        with pytest.raises(tk.NotAuthorized):
            tk.check_access(
                "rebuild_archive_index", {"user": ""}, {"id": resource["id"]}
            )

    def test_member_is_not_allowed(
        self, user: dict[str, Any], private_resource: dict[str, Any]
    ):
        """Organization member can read the resource, but not rebuild its index."""
        with pytest.raises(tk.NotAuthorized):
            tk.check_access(
                "rebuild_archive_index",
                {"user": user["name"]},
                {"id": private_resource["id"]},
            )

    def test_editor_is_allowed(
        self,
        user: dict[str, Any],
        organization_factory: types.TestFactory,
        package_factory: types.TestFactory,
        resource_factory: types.TestFactory,
    ):
        """Organization editor can rebuild the index of the org's resource."""
        org = organization_factory(users=[{"name": user["name"], "capacity": "editor"}])
        resource = resource_factory(
            package_id=package_factory(owner_org=org["id"])["id"]
        )

        tk.check_access(
            "rebuild_archive_index", {"user": user["name"]}, {"id": resource["id"]}
        )

    def test_sysadmin_is_allowed(
        self, sysadmin: dict[str, Any], resource: dict[str, Any]
    ):
        """Sysadmin can rebuild any archive index."""
        tk.check_access(
            "rebuild_archive_index", {"user": sysadmin["name"]}, {"id": resource["id"]}
        )
