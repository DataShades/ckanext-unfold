"""The plugin's IResourceView and IResourceController hooks."""

import pytest

from ckanext.unfold import utils
from ckanext.unfold.plugin import UnfoldPlugin


@pytest.fixture
def plugin() -> UnfoldPlugin:
    return UnfoldPlugin()


@pytest.fixture
def invalidated(monkeypatch) -> list[str]:
    """Resource ids whose cache the plugin asked to drop."""
    calls: list[str] = []
    monkeypatch.setattr(
        utils.UnfoldCacheManager,
        "delete",
        classmethod(lambda cls, resource_id: calls.append(resource_id)),
    )

    return calls


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [("zip", True), ("TAR.GZ", True), ("deb", True), ("csv", False), ("", False)],
)
def test_can_view_follows_the_adapter_registry(plugin, fmt: str, expected: bool):
    assert plugin.can_view({"resource": {"format": fmt}}) is expected


def test_view_info(plugin):
    info = plugin.info()

    assert info["name"] == "unfold_view"
    assert info["iframed"] is False
    assert set(info["schema"]) == {"archive_pass", "show_context_menu"}


def test_deleting_a_resource_invalidates_the_cache(plugin, invalidated):
    plugin.before_resource_delete({}, {"id": "res"}, [])

    assert invalidated == ["res"]
