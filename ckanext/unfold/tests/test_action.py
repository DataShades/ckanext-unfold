"""The ``get_archive_structure`` and ``search_archive_structure`` actions.

Datasets are created outside the HTTP mock: CKAN indexes them in Solr
over HTTP, which ``requests_mock`` would otherwise refuse.
"""

import pytest

import ckan.plugins.toolkit as tk
from ckan.tests import factories
from ckan.tests.helpers import call_action

from ckanext.unfold.logic.action import (
    _load_resource_and_view,
    _strip_password_if_unauthorized,
)
from ckanext.unfold.tests.helpers import BASE_URL, served

pytestmark = [
    pytest.mark.ckan_config("ckanext.unfold.enable_cache", False),
    pytest.mark.usefixtures("with_plugins", "clean_db", "with_request_context"),
]

ARCHIVE = "test_archive.zip"


@pytest.fixture
def archive_resource():
    """A resource whose URL serves the small zip fixture while ``served`` is active."""
    return factories.Resource(url=BASE_URL + ARCHIVE, format="zip")


def test_small_archive_is_returned_whole(archive_resource):
    with served(ARCHIVE):
        result = call_action("get_archive_structure", id=archive_resource["id"])

    assert result["mode"] == "full"
    assert result["total"] == 11
    assert len(result["nodes"]) == 11

    node = next(
        n for n in result["nodes"] if n["id"] == "test_archive/folder 1/test.xlsx"
    )
    assert node["parent"] == "test_archive/folder 1"
    assert node["state"] == {"opened": True}
    assert node["text"] == "test.xlsx"
    assert node["data"]["size"] == "5.1 KB"


def test_full_mode_never_sends_the_lazy_children_sentinel(archive_resource):
    """A folder's ``children`` must be ``False``, never the bare ``True``.

    ``True`` means "has children, not included here - fetch them lazily
    when opened" and is only correct in lazy mode. In full mode every
    descendant is already in this same flat response, so a folder left
    with ``True`` reaches jstree's flat-model loader as an unconverted
    truthy value; the moment one of its real children (a sibling entry in
    this very batch) resolves its `parent` to it, `children.push` is
    called on `true` and the whole tree fails to render.
    """
    with served(ARCHIVE):
        result = call_action("get_archive_structure", id=archive_resource["id"])

    folders = [n for n in result["nodes"] if n["id"] == "test_archive/folder 1"]
    assert folders, "fixture archive changed: no longer has this folder"
    assert folders[0]["children"] is False


@pytest.mark.ckan_config("ckanext.unfold.expand_nodes_threshold", 1)
def test_large_archive_is_served_folder_by_folder(archive_resource):
    with served(ARCHIVE):
        root = call_action("get_archive_structure", id=archive_resource["id"])
        page = call_action(
            "get_archive_structure",
            id=archive_resource["id"],
            parent="test_archive",
            limit=1,
        )
        rest = call_action(
            "get_archive_structure",
            id=archive_resource["id"],
            parent="test_archive",
            limit=10,
        )

    assert root["mode"] == "lazy"
    assert root["total"] == 11
    assert root["parent"] == "#"
    assert root["children_total"] == 1
    assert root["has_more"] is False
    assert [n["id"] for n in root["nodes"]] == ["test_archive"]
    assert root["nodes"][0]["children"] is True
    assert root["nodes"][0]["state"] == {"opened": False}
    assert "parent" not in root["nodes"][0]

    assert page["children_total"] == 2
    assert page["has_more"] is True
    assert [n["id"] for n in page["nodes"]] == ["test_archive/folder 1"]

    assert rest["has_more"] is False
    assert [n["id"] for n in rest["nodes"]] == [
        "test_archive/folder 1",
        "test_archive/folder 2",
    ]


def test_search_returns_matches_and_the_folders_to_open(archive_resource):
    with served(ARCHIVE):
        result = call_action(
            "search_archive_structure", id=archive_resource["id"], q="XLSX"
        )
        limited = call_action(
            "search_archive_structure", id=archive_resource["id"], q="xlsx", limit=1
        )

    assert result["matches"] == 2
    assert result["truncated"] is False
    assert result["ids"] == [
        "test_archive",
        "test_archive/folder 1",
        "test_archive/folder 2",
    ]
    assert [r["id"] for r in result["results"]] == [
        "test_archive/folder 1/test.xlsx",
        "test_archive/folder 2/test.xlsx",
    ]
    assert result["results"][0]["size"] == "5.1 KB"
    assert result["results"][0]["is_dir"] is False

    assert limited["matches"] == 2
    assert limited["truncated"] is True
    assert len(limited["results"]) == 1


def test_unsupported_format_is_an_error_payload():
    resource = factories.Resource(url=BASE_URL + "data.csv", format="csv")

    result = call_action("get_archive_structure", id=resource["id"])

    assert result == {
        "error": {
            "code": "unsupported_format",
            "message": "No adapter for `csv` archives",
        }
    }


def test_unreachable_archive_is_an_error_payload():
    resource = factories.Resource(url=BASE_URL + "gone.zip", format="zip")

    with served("gone.zip", b"") as mocker:
        mocker.get(BASE_URL + "gone.zip", status_code=404)
        result = call_action("get_archive_structure", id=resource["id"])

    assert list(result) == ["error"]
    assert result["error"]["code"] == "fetch_failed"
    assert result["error"]["message"].startswith("Could not fetch remote archive")


def test_archive_errors_are_logged_with_the_resource_id(caplog):
    resource = factories.Resource(url=BASE_URL + "data.csv", format="csv")

    with caplog.at_level("WARNING", logger="ckanext.unfold.logic.action"):
        call_action("get_archive_structure", id=resource["id"])
        call_action("search_archive_structure", id=resource["id"], q="x")

    records = [r for r in caplog.records if r.name == "ckanext.unfold.logic.action"]

    assert len(records) == 2
    assert all(r.levelname == "WARNING" for r in records)
    assert all(resource["id"] in r.getMessage() for r in records)
    assert "unsupported_format" in records[0].getMessage()


def test_view_of_another_resource_is_rejected(archive_resource):
    other = factories.Resource(
        package_id=archive_resource["package_id"],
        url=BASE_URL + "other.zip",
        format="zip",
    )
    view = call_action(
        "resource_view_create",
        resource_id=other["id"],
        view_type="unfold_view",
        title="Unfold",
    )

    with served(ARCHIVE), pytest.raises(tk.ValidationError) as info:
        call_action(
            "get_archive_structure", id=archive_resource["id"], view_id=view["id"]
        )

    assert info.value.error_dict == {"view_id": ["View does not belong to resource"]}


def test_unknown_ids_fail_validation(archive_resource):
    with pytest.raises(tk.ValidationError):
        call_action("get_archive_structure", id="does-not-exist")

    with pytest.raises(tk.ValidationError):
        call_action(
            "get_archive_structure", id=archive_resource["id"], view_id="does-not-exist"
        )

    with pytest.raises(tk.ValidationError):
        call_action("search_archive_structure", id=archive_resource["id"], q="")


def test_private_dataset_requires_read_access():
    member = factories.User()
    org = factories.Organization(users=[{"name": member["name"], "capacity": "member"}])
    dataset = factories.Dataset(owner_org=org["id"], private=True)
    resource = factories.Resource(
        package_id=dataset["id"], url=BASE_URL + ARCHIVE, format="zip"
    )

    with served(ARCHIVE):
        with pytest.raises(tk.NotAuthorized):
            call_action(
                "get_archive_structure",
                {"user": "", "ignore_auth": False},
                id=resource["id"],
            )

        result = call_action(
            "get_archive_structure",
            {"user": member["name"], "ignore_auth": False},
            id=resource["id"],
        )

    assert result["mode"] == "full"


@pytest.fixture
def password_protected_resource():
    """A password-protected RAR resource with ``archive_pass`` on its unfold
    view, in an org where ``editor`` can update the resource and ``member``
    can only read it. RAR is the format whose adapter actually reads
    ``archive_pass`` to unlock the listing (see ``adapters/rar.py``).
    """
    editor = factories.User()
    member = factories.User()
    org = factories.Organization(
        users=[
            {"name": editor["name"], "capacity": "editor"},
            {"name": member["name"], "capacity": "member"},
        ]
    )
    dataset = factories.Dataset(owner_org=org["id"])
    resource = factories.Resource(
        package_id=dataset["id"], url=BASE_URL + "secret.rar", format="rar"
    )
    view = call_action(
        "resource_view_create",
        resource_id=resource["id"],
        view_type="unfold_view",
        title="Unfold",
        archive_pass="secret",  # noqa: S106
    )

    return {"editor": editor, "member": member, "resource": resource, "view": view}


def test_password_is_hidden_from_users_without_update_access(
    password_protected_resource,
):
    member = password_protected_resource["member"]
    editor = password_protected_resource["editor"]
    view_id = password_protected_resource["view"]["id"]

    anon = call_action(
        "resource_view_show", {"user": "", "ignore_auth": False}, id=view_id
    )
    assert anon["archive_pass"] is None

    as_member = call_action(
        "resource_view_show",
        {"user": member["name"], "ignore_auth": False},
        id=view_id,
    )
    assert as_member["archive_pass"] is None

    as_editor = call_action(
        "resource_view_show",
        {"user": editor["name"], "ignore_auth": False},
        id=view_id,
    )
    assert as_editor["archive_pass"] == "secret"  # noqa: S105

    as_sysadmin = call_action("resource_view_show", id=view_id)
    assert as_sysadmin["archive_pass"] == "secret"  # noqa: S105


def test_password_is_hidden_in_resource_view_list_too(password_protected_resource):
    member = password_protected_resource["member"]
    resource_id = password_protected_resource["resource"]["id"]

    views = call_action(
        "resource_view_list",
        {"user": member["name"], "ignore_auth": False},
        id=resource_id,
    )

    assert len(views) == 1
    assert views[0]["archive_pass"] is None


def test_other_view_types_are_left_alone():
    """The helper is scoped to unfold views; a plain dict is enough here --
    it never reaches ``check_access`` (and so needs no resource/DB at all)
    because the ``view_type`` check short-circuits first.
    """
    view = {
        "view_type": "text_view",
        "archive_pass": "secret",
        "resource_id": "does-not-matter",
    }

    _strip_password_if_unauthorized({"user": "", "ignore_auth": False}, view)

    assert view["archive_pass"] == "secret"  # noqa: S105


def test_password_is_available_internally_for_read_only_users(
    password_protected_resource,
):
    """``_load_resource_and_view`` must still see the real password for a
    user without ``resource_update``, since it is used server side to unlock
    a protected archive -- only ``resource_view_show``/``resource_view_list``
    (called directly by a caller) strip it.
    """
    member = password_protected_resource["member"]
    resource_id = password_protected_resource["resource"]["id"]
    view_id = password_protected_resource["view"]["id"]

    _, resource_view = _load_resource_and_view(
        {"user": member["name"], "ignore_auth": False},
        {"id": resource_id, "view_id": view_id},
    )

    assert resource_view["archive_pass"] == "secret"  # noqa: S105
