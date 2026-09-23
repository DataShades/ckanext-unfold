"""The validators behind the view and action schemas, against the database.

``show_context_menu`` is covered in ``test_action.py``; this covers the id
validators every action shares, ``limit``/``q`` on the actions that take them
and the view schema's ``archive_pass``.
"""

import pytest

import ckan.plugins.toolkit as tk
from ckan.tests import factories
from ckan.tests.helpers import call_action

from ckanext.unfold.tests.helpers import BASE_URL, served

pytestmark = [
    pytest.mark.ckan_config("ckanext.unfold.enable_cache", False),
    pytest.mark.usefixtures("with_plugins", "clean_db", "with_request_context"),
]

ACTIONS = ["get_archive_structure", "search_archive_structure", "get_archive_status"]


def params(action: str, **data: str) -> dict[str, str]:
    """``data`` plus whatever the action cannot do without."""
    if action == "search_archive_structure":
        data.setdefault("q", "readme")

    return data


@pytest.fixture
def resource():
    return factories.Resource(url=BASE_URL + "test_archive.zip", format="zip")


def create_view(resource_id: str, **data) -> dict:
    return call_action(
        "resource_view_create",
        resource_id=resource_id,
        view_type="unfold_view",
        title="Unfold",
        **data,
    )


def test_resource_view_id_exists(resource):
    validator = tk.get_validator("resource_view_id_exists")
    view = create_view(resource["id"])

    assert validator(view["id"], {}) == view["id"]

    with pytest.raises(tk.Invalid, match="Resource view not found"):
        validator("does-not-exist", {})


@pytest.mark.parametrize("action", ACTIONS)
def test_resource_id_is_required_and_must_exist(action):
    with pytest.raises(tk.ValidationError) as missing:
        call_action(action, **params(action))

    assert "id" in missing.value.error_dict

    with pytest.raises(tk.ValidationError) as unknown:
        call_action(action, **params(action, id="does-not-exist"))

    assert "id" in unknown.value.error_dict


@pytest.mark.parametrize("action", ACTIONS)
def test_view_id_must_exist(action, resource):
    with pytest.raises(tk.ValidationError) as info:
        call_action(action, **params(action, id=resource["id"], view_id="nope"))

    assert set(info.value.error_dict) == {"view_id"}


@pytest.mark.parametrize("action", ACTIONS)
def test_view_must_belong_to_the_resource(action, resource):
    other = factories.Resource(
        package_id=resource["package_id"], url=BASE_URL + "other.zip", format="zip"
    )
    view = create_view(other["id"])

    with pytest.raises(tk.ValidationError) as info:
        call_action(action, **params(action, id=resource["id"], view_id=view["id"]))

    assert info.value.error_dict == {"view_id": ["View does not belong to resource"]}


@pytest.mark.parametrize("action", ACTIONS)
def test_the_view_of_the_resource_is_accepted(action, resource):
    view = create_view(resource["id"])

    with served("test_archive.zip"):
        result = call_action(
            action, **params(action, id=resource["id"], view_id=view["id"])
        )

    assert "error" not in result


def test_empty_optional_arguments_are_ignored(resource):
    """The widget sends whatever it has, so blanks must not fail validation."""
    with served("test_archive.zip"):
        result = call_action(
            "get_archive_structure",
            id=resource["id"],
            view_id="",
            parent="",
            limit="",
        )

    assert result["mode"] == "full"


@pytest.mark.parametrize(
    "action", ["get_archive_structure", "search_archive_structure"]
)
def test_limit_must_be_an_integer(action, resource):
    with pytest.raises(tk.ValidationError) as info:
        call_action(action, **params(action, id=resource["id"], limit="many"))

    assert set(info.value.error_dict) == {"limit"}


def test_limit_arrives_as_text_over_http(resource):
    """Query-string and form values are strings; ``int_validator`` converts them."""
    with served("test_archive.zip"):
        result = call_action(
            "search_archive_structure", id=resource["id"], q="xlsx", limit="1"
        )

    assert result["matches"] == 2
    assert result["truncated"] is True
    assert len(result["results"]) == 1


def test_search_needs_a_query(resource):
    with pytest.raises(tk.ValidationError) as info:
        call_action("search_archive_structure", id=resource["id"])

    assert set(info.value.error_dict) == {"q"}


def test_empty_password_is_not_stored(resource):
    view = create_view(resource["id"], archive_pass="")

    assert "archive_pass" not in view


def test_password_is_stored_as_text(resource):
    view = create_view(resource["id"], archive_pass="s3cret")  # noqa: S106

    assert view["archive_pass"] == "s3cret"  # noqa: S105


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        (True, True),
        (False, False),
        ("yes", True),
        ("1", True),
        ("no", False),
        ("0", False),
    ],
)
def test_context_menu_accepts_the_usual_spellings_of_a_boolean(resource, value, stored):
    view = create_view(resource["id"], show_context_menu=value)

    assert view["show_context_menu"] is stored


def test_context_menu_can_be_switched_off_later(resource):
    view = create_view(resource["id"], show_context_menu="true")

    updated = call_action(
        "resource_view_update",
        id=view["id"],
        title="Unfold",
        show_context_menu="false",
    )

    assert updated["show_context_menu"] is False
