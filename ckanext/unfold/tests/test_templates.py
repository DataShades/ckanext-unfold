"""``unfold_preview.html`` and ``unfold_form.html``, rendered once each.

The preview is rendered the way CKAN does it (``h.rendered_resource_view``),
which also runs the plugin's ``view_template`` and ``setup_template_variables``.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

import ckan.plugins.toolkit as tk

import ckanext.unfold.config as unf_config

pytestmark = pytest.mark.usefixtures("with_plugins", "with_request_context")

MODULE_JS = Path(__file__).parents[1] / "assets" / "js" / "unfold-init-jstree.js"


class Page(HTMLParser):
    """The elements of a rendered template, for asserting on without a browser."""

    def __init__(self, html: str):
        super().__init__()
        self.elements: list[tuple[str, dict[str, str]]] = []
        self.options: list[dict[str, str]] = []
        self._in_option = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        self.elements.append((tag, attributes))

        if tag == "option":
            self.options.append({**attributes, "text": ""})
            self._in_option = True

    def handle_endtag(self, tag):
        if tag == "option":
            self._in_option = False

    def handle_data(self, data):
        if self._in_option:
            self.options[-1]["text"] += data.strip()

    def with_class(self, name: str) -> list[dict[str, str]]:
        return [
            attrs
            for _, attrs in self.elements
            if name in attrs.get("class", "").split()
        ]

    def one(self, name: str) -> dict[str, str]:
        found = self.with_class(name)
        assert len(found) == 1, f"expected one .{name}, found {len(found)}"

        return found[0]

    def selected(self) -> list[str]:
        return [option["text"] for option in self.options if "selected" in option]


def render_preview(**view) -> Page:
    resource = {"id": "res-1"}
    resource_view = {
        "id": "view-1",
        "view_type": "unfold_view",
        "resource_id": resource["id"],
        **view,
    }
    html = tk.h.rendered_resource_view(resource_view, resource, {"id": "pkg-1"})

    return Page(str(html))


def render_form(data: dict | None = None, errors: dict | None = None) -> Page:
    html = tk.render(
        "unfold_form.html",
        extra_vars={
            "data": data or {},
            "errors": errors or {},
            "show_context_menu_default": unf_config.get_context_menu_default(),
        },
    )

    return Page(html)


def test_preview_hands_the_module_its_options(monkeypatch):
    monkeypatch.setitem(tk.config, unf_config.CONF_PAGE_SIZE, 250)

    widget = render_preview().one("unfold-preview")

    assert widget["data-module"] == "unfold-init-jstree"
    assert widget["data-module-resource-id"] == "res-1"
    assert widget["data-module-resource-view-id"] == "view-1"
    assert widget["data-module-page-size"] == "250"


@pytest.mark.parametrize(
    ("default", "stored", "expected"),
    [
        (True, None, "true"),
        (False, None, "false"),
        (True, False, "false"),
        (False, True, "true"),
    ],
)
def test_preview_context_menu_follows_the_view_then_the_default(
    monkeypatch, default, stored, expected
):
    monkeypatch.setitem(tk.config, unf_config.CONF_CONTEXT_MENU, default)
    view = {} if stored is None else {"show_context_menu": stored}

    widget = render_preview(**view).one("unfold-preview")

    assert widget["data-module-show-context-menu"] == expected


def test_preview_has_every_element_the_module_looks_up():
    """``unfold-init-jstree.js`` finds its parts by class; a rename on either
    side would leave a widget that loads and silently does nothing."""
    source = MODULE_JS.read_text()
    selectors = {
        selector.strip()
        for group in re.findall(r'\.find\("([^"]+)"\)', source)
        for selector in group.split(",")
    }

    assert len(selectors) > 10, "the pattern no longer matches the module"

    page = render_preview()

    for selector in sorted(selectors):
        assert selector.startswith("."), f"unexpected selector {selector!r}"
        assert page.with_class(selector[1:]), f"template has no {selector}"


def test_preview_starts_quiet():
    """Nothing is shown or usable until the module has loaded the listing."""
    page = render_preview()

    for name in [
        "unf-tree-error",
        "unf-tree-retry",
        "unf-tree-processing",
        "unfold-search-results",
        "jstree-search-clear",
    ]:
        assert "hidden" in page.one(name), f".{name} must start hidden"

    for name in [
        "unf-search-input",
        "unf-search-run",
        "unf-expand-all",
        "unf-collapse-all",
    ]:
        assert "disabled" in page.one(name), f".{name} must start disabled"


def test_preview_is_announced_to_assistive_technology():
    page = render_preview()

    assert page.one("unf-tree-error")["role"] == "alert"
    assert page.one("unfold-toast")["role"] == "status"
    assert page.one("unfold-load-state")["role"] == "status"
    assert page.one("unfold-tree-meta")["aria-live"] == "polite"
    assert page.one("unfold-search-results")["aria-live"] == "polite"
    assert page.one("unf-search-input")["aria-label"]

    for name in [
        "jstree-search-clear",
        "unf-search-run",
        "unf-expand-all",
        "unf-collapse-all",
    ]:
        assert page.one(name)["aria-label"], f".{name} has no accessible name"


def test_form_asks_for_a_password():
    field = render_form()

    password = next(a for t, a in field.elements if a.get("name") == "archive_pass")

    assert password["type"] == "password"
    assert password["id"] == "field-password"
    assert password["value"] == ""


def test_form_shows_the_stored_password_and_errors():
    """The field is pre-filled: saving the form again must not wipe it."""
    page = render_form(
        data={"archive_pass": "s3cret"}, errors={"archive_pass": ["Not good"]}
    )

    password = next(a for t, a in page.elements if a.get("name") == "archive_pass")

    assert password["value"] == "s3cret"
    assert page.with_class("error-block"), "the field's error is not shown"


@pytest.mark.parametrize(
    ("default", "stored", "expected"),
    [
        (True, None, "Yes"),
        (False, None, "No"),
        (True, False, "No"),
        (False, True, "Yes"),
    ],
)
def test_form_preselects_the_stored_setting_or_the_default(
    monkeypatch, default, stored, expected
):
    monkeypatch.setitem(tk.config, unf_config.CONF_CONTEXT_MENU, default)
    data = {} if stored is None else {"show_context_menu": stored}

    page = render_form(data=data)

    assert [option["text"] for option in page.options] == ["Yes", "No"]
    assert page.selected() == [expected]
