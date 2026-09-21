"""Work out which adapter-registry key a resource's format belongs to.

CKAN users type the format freely, so the registry key (``zip``, ``tar.gz``)
is only one of many spellings: ``TGZ``, ``application/zip``, ``Zip Archive``.
The label can also be too coarse (``TAR`` on a ``.tar.gz`` file) or missing,
while the URL still ends in the real file name.

This module has no CKAN dependency: it only maps strings to registry keys.
"""

from __future__ import annotations

import re
from collections.abc import Container
from urllib.parse import unquote, urlparse


ALIASES: dict[str, str] = {
    # tar variants
    "tgz": "tar.gz",
    "taz": "tar.gz",
    "tar.gzip": "tar.gz",
    "tbz": "tar.bz2",
    "tbz2": "tar.bz2",
    "tb2": "tar.bz2",
    "tar.bz": "tar.bz2",
    "txz": "tar.xz",
    "application/x-tar": "tar",
    "application/x-gtar": "tar",
    "application/x-compressed-tar": "tar.gz",
    # zip variants
    "application/zip": "zip",
    "application/x-zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/zip-compressed": "zip",
    "application/java-archive": "jar",
    # the rest
    "7zip": "7z",
    "7-zip": "7z",
    "application/x-7z-compressed": "7z",
    "application/rar": "rar",
    "application/x-rar": "rar",
    "application/x-rar-compressed": "rar",
    "application/vnd.rar": "rar",
    "application/vnd.comicbook-rar": "cbr",
    "application/x-cbr": "cbr",
    "application/x-debian-package": "deb",
    "application/vnd.debian.binary-package": "deb",
    "application/x-rpm": "rpm",
    "application/x-redhat-package-manager": "rpm",
    "application/x-archive": "ar",
    "application/x-unix-archive": "ar",
}

# A label's noise words: "Zip Archive", "TAR Compressed File"
_NOISE_SUFFIX = re.compile(r"\s+(?:compressed\s+)?(?:archive|file)$")


def normalize(label: str | None) -> str:
    """Reduce a free-text format to a registry key or a known alias target."""
    text = (label or "").split(";")[0].strip().lower()  # MIME type parameters
    text = _NOISE_SUFFIX.sub("", re.sub(r"\s+", " ", text)).lstrip(".").strip()

    return ALIASES.get(text, text)


def extension_key(url: str | None, known: Container[str]) -> str | None:
    """Return the registry key the URL's file name ends with, if any.

    Tries the two-part extension (``tar.gz``) before the one-part one, so a
    ``.tar.gz`` is not taken for a plain gzip.
    """
    if not url:
        return None

    name = unquote(urlparse(url).path).rsplit("/", 1)[-1].lower()
    parts = name.split(".")

    for size in (2, 1):
        if len(parts) <= size:
            continue

        suffix = ".".join(parts[-size:])
        key = ALIASES.get(suffix, suffix)

        if key in known:
            return key

    return None


def resolve(label: str | None, url: str | None, known: Container[str]) -> str | None:
    """Return the key in ``known`` for a resource, or ``None`` if there is none.

    The label wins when it names a known format, except that a URL extension
    which is a more specific form of it takes over: ``TAR`` on ``x.tgz``
    means ``tar.gz``, and a plain ``tar`` adapter would fail on it. When the
    label names nothing known (blank, ``Archive``, or ``GZ``, which may be a
    tarball or one compressed file), the URL's extension is used.
    """
    by_label = normalize(label)
    by_url = extension_key(url, known)

    if by_label not in known:
        return by_url

    if by_url and by_url.startswith(f"{by_label}."):
        return by_url

    return by_label
