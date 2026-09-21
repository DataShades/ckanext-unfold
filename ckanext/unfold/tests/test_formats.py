"""Mapping a resource's free-text format and URL to an adapter key."""

import pytest

from ckanext.unfold import formats

KNOWN = {
    "rar",
    "cbr",
    "7z",
    "zip",
    "zipx",
    "jar",
    "tar",
    "tar.gz",
    "tar.xz",
    "tar.bz2",
    "rpm",
    "deb",
    "ar",
    "a",
    "lib",
}


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("zip", "zip"),
        ("ZIP", "zip"),
        (" Zip ", "zip"),
        (".zip", "zip"),
        ("Zip Archive", "zip"),
        ("Zip File", "zip"),
        ("application/zip", "zip"),
        ("application/zip; charset=binary", "zip"),
        ("application/x-zip-compressed", "zip"),
        ("TGZ", "tar.gz"),
        (".tgz", "tar.gz"),
        ("TBZ2", "tar.bz2"),
        ("txz", "tar.xz"),
        ("TAR Compressed File", "tar"),
        ("application/x-tar", "tar"),
        ("7-Zip", "7z"),
        ("application/vnd.rar", "rar"),
        ("application/java-archive", "jar"),
        ("application/x-debian-package", "deb"),
        ("application/x-rpm", "rpm"),
        ("tar.gz", "tar.gz"),
    ],
)
def test_label_spellings_reach_the_registry_key(label: str, expected: str):
    assert formats.resolve(label, None, KNOWN) == expected


@pytest.mark.parametrize("label", ["csv", "", None, "GZ", "gzip", "application/gzip"])
def test_unknown_label_without_url_matches_nothing(label: str | None):
    """A bare ``GZ`` may be one compressed file, so it is not a tar.gz."""
    assert formats.resolve(label, None, KNOWN) is None


@pytest.mark.parametrize(
    ("label", "url", "expected"),
    [
        # the label is too coarse, the file name is exact
        ("TAR", "http://x.test/data.tar.gz", "tar.gz"),
        ("tar", "http://x.test/data.tgz", "tar.gz"),
        ("tar", "http://x.test/data.tar.xz", "tar.xz"),
        ("tar", "http://x.test/data.tbz2", "tar.bz2"),
        # a compression-only label is completed by the URL...
        ("GZ", "http://x.test/data.tar.gz", "tar.gz"),
        ("application/gzip", "http://x.test/data.tgz", "tar.gz"),
        # ...but a lone .gz is not a tarball
        ("GZ", "http://x.test/data.csv.gz", None),
        ("GZ", "http://x.test/data.gz", None),
        # no or unusable label: the extension decides
        ("", "http://x.test/data.zip", "zip"),
        (None, "http://x.test/data.tar.bz2", "tar.bz2"),
        ("Archive", "http://x.test/data.7z", "7z"),
        ("csv", "http://x.test/data.csv.zip", "zip"),
        # the label wins when it is a known format that the URL only disagrees with
        ("zip", "http://x.test/download?id=3", "zip"),
        ("tar.gz", "http://x.test/data.tar", "tar.gz"),
        ("zip", "http://x.test/data.jar", "zip"),
        ("zip", "http://x.test/data.tar.gz", "zip"),
        # the query string, fragment, case and percent-encoding are not the name
        ("", "http://x.test/Data.TAR.GZ?token=a.zip#frag", "tar.gz"),
        ("", "http://x.test/my%20data.zip", "zip"),
        ("", "http://x.test/dl/data.zip/", None),
        # a name without a dot has no extension
        ("", "http://x.test/zip", None),
        ("", "", None),
    ],
)
def test_url_extension(label: str | None, url: str, expected: str | None):
    assert formats.resolve(label, url, KNOWN) == expected


def test_only_keys_of_the_registry_are_returned():
    """A subscriber that registers its own key extends the lookup."""
    known = {*KNOWN, "my.format", "zst"}

    assert formats.resolve("", "http://x.test/a.my.format", known) == "my.format"
    assert formats.resolve("", "http://x.test/a.zst", known) == "zst"
    assert formats.resolve("", "http://x.test/a.zst", KNOWN) is None
    assert formats.resolve("zst", None, KNOWN) is None
