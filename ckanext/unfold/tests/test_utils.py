"""Adapter lookup, the adapter signal, and small helpers."""

import pytest

from ckanext.unfold import exception, utils
from ckanext.unfold.adapters import adapter_registry, tar
from ckanext.unfold.adapters.zip import ZipAdapter


class CustomAdapter(ZipAdapter):
    pass


@pytest.fixture
def subscribe():
    """Connect a receiver to the adapter signal for the test's duration."""
    receivers = []

    def connect(receiver):
        utils.get_adapter_for_resource_signal.connect(receiver)
        receivers.append(receiver)
        return receiver

    yield connect

    for receiver in receivers:
        utils.get_adapter_for_resource_signal.disconnect(receiver)


def test_registry_lookup_is_case_insensitive():
    assert utils.get_adapter_for_resource({"format": "ZIP"}) is adapter_registry["zip"]
    assert utils.get_adapter_for_resource({"format": "Tar.GZ"}) is tar.TarGzAdapter
    assert utils.get_adapter_for_resource({"format": "csv"}) is None
    assert utils.get_adapter_for_resource({"format": ""}) is None


@pytest.mark.parametrize(
    ("resource", "adapter"),
    [
        ({"format": "TGZ"}, tar.TarGzAdapter),
        ({"format": "application/zip"}, ZipAdapter),
        ({"format": "Zip Archive"}, ZipAdapter),
        ({"format": "TAR", "url": "http://x.test/a.tar.gz"}, tar.TarGzAdapter),
        ({"format": "TAR", "url": "http://x.test/a.tar"}, tar.TarAdapter),
        ({"format": "", "url": "http://x.test/a.tar.xz?x=1"}, tar.TarXzAdapter),
        ({"format": "GZ", "url": "http://x.test/a.tgz"}, tar.TarGzAdapter),
        ({"format": "GZ", "url": "http://x.test/a.gz"}, None),
        ({"format": "csv", "url": "http://x.test/a.csv"}, None),
        ({"format": "csv"}, None),
    ],
)
def test_adapter_lookup_normalizes_format_and_reads_url(resource, adapter):
    assert utils.get_adapter_for_resource(resource) is adapter


def test_signal_receiver_can_provide_an_adapter(subscribe):
    subscribe(lambda resource: CustomAdapter if resource["format"] == "csv" else None)

    assert utils.get_adapter_for_resource({"format": "csv"}) is CustomAdapter
    # None from every receiver falls through to the registry
    assert utils.get_adapter_for_resource({"format": "zip"}) is adapter_registry["zip"]


def test_signal_receiver_returning_false_leaves_the_registry_in_charge(subscribe):
    """``False`` stops consulting receivers; it does not disable the format."""
    subscribe(lambda resource: False)

    assert utils.get_adapter_for_resource({"format": "zip"}) is adapter_registry["zip"]
    assert utils.get_adapter_for_resource({"format": "csv"}) is None


def test_signal_receiver_returning_no_preview_disables_the_format(subscribe):
    """Unlike ``False``, ``NO_PREVIEW`` also skips the default registry."""
    subscribe(lambda resource: utils.NO_PREVIEW)

    assert utils.get_adapter_for_resource({"format": "zip"}) is None
    assert utils.get_adapter_for_resource({"format": "csv"}) is None


def test_no_preview_overrides_an_adapter_from_a_later_receiver(subscribe):
    """A `NO_PREVIEW` result wins even if a later receiver offers an adapter.

    `signal.send()` calls every receiver regardless (blinker has no way to
    short-circuit it), so this is about which *result* `get_adapter_for_resource`
    picks, not about skipping the call itself.
    """
    subscribe(lambda resource: utils.NO_PREVIEW)
    subscribe(lambda resource: CustomAdapter)

    assert utils.get_adapter_for_resource({"format": "zip"}) is None


def test_get_archive_tree_reports_unknown_format():
    resource = {"format": "CSV", "url": "http://archives.test/x.csv"}

    with pytest.raises(exception.UnfoldError, match="No adapter for `csv` archives"):
        utils.get_archive_tree(resource, {})
