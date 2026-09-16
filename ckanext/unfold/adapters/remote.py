"""HTTP access to remote archives.

Two ways of reading a remote file are provided:

* :func:`fetch_full` downloads the whole body, aborting once the configured
  byte limit is exceeded. Used for formats whose index cannot be read without
  the whole file (tar, rar, 7z, ...).
* :func:`open_remote` returns a seekable file object backed by HTTP Range
  requests. Formats that keep their index at known offsets (zip) can then be
  parsed while transferring only the parts the parser actually reads. This is
  what makes archives far above the byte limit previewable: for a zip only
  the end-of-central-directory records and the central directory are fetched.

This module deliberately depends on ``requests`` only, so it can be tested
without a CKAN runtime.
"""

from __future__ import annotations

import io
import ipaddress
import logging
import socket
import time
from typing import IO
from urllib.parse import urljoin, urlparse

import requests

import ckan.plugins.toolkit as tk

from ckanext.unfold.exception import UnfoldError
from ckanext.unfold.formatting import printable_file_size

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60  # seconds, per request (connect and per-read)
# wall-clock budget for all Range requests of one archive read
TOTAL_TIME_BUDGET = 120  # seconds
CHUNK_SIZE = 64 * 1024
# zipfile reads an archive back to front: EOCD record, ZIP64 records, then
# the central directory. Fetching in fixed blocks keeps the number of Range
# requests small while transferring little more than what the parser reads.
BLOCK_SIZE = 256 * 1024

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECTS = 5


def limit_message(max_bytes: int) -> str:
    return tk._("Archive exceeds maximum allowed size for processing: %(size)s") % {
        "size": printable_file_size(max_bytes)
    }


def check_limit(size: int | None, max_bytes: int) -> None:
    """Raise if ``size`` exceeds ``max_bytes``. ``None`` (unknown) passes."""
    if size is not None and size > max_bytes:
        raise UnfoldError(limit_message(max_bytes))


def content_length(value: str | None) -> int | None:
    """Parse a Content-Length header value."""
    if value and value.isdigit():
        return int(value)

    return None


def total_from_content_range(value: str | None) -> int | None:
    """Extract the total size from a Content-Range value, e.g. "bytes 0-9/100"."""
    if not value or "/" not in value:
        return None

    total = value.rsplit("/", 1)[-1].strip()

    return int(total) if total.isdigit() else None


def _resolves_to_public_address(hostname: str) -> bool:
    """Whether every address ``hostname`` resolves to is publicly routable.

    A resource URL is set by whoever creates the resource, and every archive
    view triggers a server-side GET to it, so without this an editor (or an
    imported/harvested dataset) could point the server at loopback,
    link-local or RFC 1918 addresses -- cloud instance metadata endpoints and
    internal admin ports included.

    A hostname that fails to resolve at all is let through: the request will
    simply fail the same way immediately afterwards (same resolver, same
    result), so blocking it here would add no protection -- and it keeps
    documentation/test hostnames (the reserved ``.test`` TLD, for instance)
    working without a real DNS record.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return True

    for info in infos:
        ip = info[4][0]

        try:
            if not ipaddress.ip_address(ip).is_global:
                return False
        except ValueError:
            return False

    return True


def validate_url(url: str) -> None:
    """Reject a URL that is unsafe for the server to fetch on the caller's
    behalf (SSRF hardening): only ``http``/``https`` with a host that
    resolves exclusively to publicly routable addresses is allowed.

    The failure is reported generically and logged with the detail server
    side, rather than surfacing the resolved address or the reason to the
    caller.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        log.warning("Refusing to fetch %s: not an http(s) URL", url)
        raise UnfoldError(tk._("Could not fetch the archive"))

    if not _resolves_to_public_address(parsed.hostname):
        log.warning("Refusing to fetch %s: resolves to a non-public address", url)
        raise UnfoldError(tk._("Could not fetch the archive"))


def safe_get(
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    stream: bool = False,
) -> requests.Response:
    """A ``requests.get`` that blocks unsafe destinations (see
    ``validate_url``) and never follows a redirect without re-validating it
    first -- a URL that passes the check can otherwise 302 straight to a
    blocked address.
    """
    for _ in range(MAX_REDIRECTS + 1):
        validate_url(url)

        resp = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            stream=stream,
            allow_redirects=False,
        )

        if not (resp.is_redirect or resp.is_permanent_redirect):
            return resp

        location = resp.headers.get("location")
        resp.close()

        if not location:
            raise UnfoldError(tk._("Could not fetch the archive"))

        url = urljoin(url, location)

    raise UnfoldError(tk._("Too many redirects while fetching the archive"))


def read_limited(resp: requests.Response, max_bytes: int) -> bytes:
    """Read a streamed response body, aborting once it exceeds ``max_bytes``.

    Protects against missing or wrong Content-Length headers: an over-limit
    body is never fully loaded into memory.
    """
    chunks: list[bytes] = []
    downloaded = 0

    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
        downloaded += len(chunk)
        check_limit(downloaded, max_bytes)
        chunks.append(chunk)

    return b"".join(chunks)


def fetch_full(url: str, max_bytes: int, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """Download a whole remote file within ``max_bytes``."""
    started = time.monotonic()
    log.info("Downloading %s (limit %s bytes)", url, max_bytes)

    try:
        with safe_get(url, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            check_limit(content_length(resp.headers.get("content-length")), max_bytes)

            data = read_limited(resp, max_bytes)
    except requests.RequestException as e:
        raise UnfoldError(
            tk._("Could not fetch archive: %(error)s") % {"error": e}
        ) from e

    log.info(
        "Downloaded %s bytes from %s in %.1fs",
        len(data),
        url,
        time.monotonic() - started,
    )
    return data


class RemoteRangeFile(io.RawIOBase):
    """Seekable, read-only view of a remote file using HTTP Range requests.

    The object reports the real file size, so parsers that seek to absolute
    offsets (``zipfile`` with ZIP64 records, for instance) work unchanged.
    Data is fetched in ``block_size`` blocks on first access and kept in
    memory; ``max_bytes`` caps the total transferred.
    """

    def __init__(
        self,
        url: str,
        size: int,
        max_bytes: int,
        *,
        block_size: int = BLOCK_SIZE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__()
        self.url = url
        self.size = size
        self.max_bytes = max_bytes
        self.block_size = block_size
        self.timeout = timeout
        self.bytes_fetched = 0
        self.requests_made = 0
        self.started = time.monotonic()
        self.deadline = self.started + TOTAL_TIME_BUDGET
        self._pos = 0
        self._ranges: dict[int, bytes] = {}  # start offset -> data

    def close(self) -> None:
        if not self.closed:
            log.info(
                "Read %s bytes of %s in %s Range requests, %.1fs: %s",
                self.bytes_fetched,
                self.size,
                self.requests_made,
                time.monotonic() - self.started,
                self.url,
            )
        super().close()

    # io.RawIOBase interface

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            pos = offset
        elif whence == io.SEEK_CUR:
            pos = self._pos + offset
        elif whence == io.SEEK_END:
            pos = self.size + offset
        else:
            raise ValueError(f"invalid whence: {whence}")

        if pos < 0:
            raise ValueError("negative seek position")

        self._pos = pos
        return pos

    def readinto(self, buffer: bytearray) -> int:  # type: ignore[override]
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            size = self.size - self._pos

        out = bytearray()

        while size > 0 and self._pos < self.size:
            hit = self._cached(self._pos)

            if hit is None:
                # Fetch the whole span the caller asked for in one request
                # (zipfile reads the central directory with a single read),
                # but never less than one block so small seeks stay cheap.
                # Align both ends to block boundaries so a buffered reader's
                # read-ahead lands inside what was already fetched.
                start = (self._pos // self.block_size) * self.block_size
                wanted = max(self._pos + size, start + self.block_size)
                aligned_end = -(-wanted // self.block_size) * self.block_size
                end = min(aligned_end, self.size) - 1
                self.seed(start, self._fetch(start, end))
                continue

            start, data = hit
            offset = self._pos - start
            chunk = data[offset : offset + size]
            out += chunk
            self._pos += len(chunk)
            size -= len(chunk)

        return bytes(out)

    # helpers

    def seed(self, start: int, data: bytes) -> None:
        """Register already-downloaded bytes starting at ``start``."""
        if data:
            self._ranges[start] = data

    def _cached(self, pos: int) -> tuple[int, bytes] | None:
        for start, data in self._ranges.items():
            if start <= pos < start + len(data):
                return start, data

        return None

    def _fetch(self, start: int, end: int) -> bytes:
        wanted = end - start + 1
        check_limit(self.bytes_fetched + wanted, self.max_bytes)

        if time.monotonic() > self.deadline:
            raise UnfoldError(
                tk._("Reading the remote archive took longer than %(seconds)s seconds")
                % {"seconds": TOTAL_TIME_BUDGET}
            )

        log.info(
            "Range request %s: bytes %s-%s of %s from %s",
            self.requests_made + 1,
            start,
            end,
            self.size,
            self.url,
        )

        try:
            with safe_get(
                self.url,
                headers={"Range": f"bytes={start}-{end}"},
                timeout=self.timeout,
                stream=True,
            ) as resp:
                resp.raise_for_status()

                if resp.status_code != requests.codes.partial_content:
                    raise UnfoldError(
                        tk._(
                            "The server does not support partial downloads (HTTP Range)"
                        )
                    )

                # Bounded to `wanted`, not just `max_bytes`: a server that
                # returns 206 but ignores the requested end of the range (or
                # lies about it) must not buffer more than what was asked for.
                data = read_limited(resp, wanted)
        except requests.RequestException as e:
            raise UnfoldError(
                tk._("Could not fetch remote archive: %(error)s") % {"error": e}
            ) from e

        if len(data) != wanted:
            raise UnfoldError(tk._("The server returned an incomplete byte range"))

        self.bytes_fetched += len(data)
        self.requests_made += 1

        return data


def open_remote(
    url: str,
    max_bytes: int,
    timeout: float = DEFAULT_TIMEOUT,
    block_size: int = BLOCK_SIZE,
) -> IO[bytes]:
    """Open a remote file for random access as a binary file object.

    A suffix Range request for the last block probes the server and, for
    archive formats with a trailing index, already delivers most of what the
    parser needs. Depending on the answer:

    * ``206``: the server supports ranges. A :class:`RemoteRangeFile` seeded
      with the tail is returned; further blocks are fetched on demand within
      ``max_bytes``.
    * ``416``: the file is smaller than one block and the server rejects the
      oversized suffix. The whole file is fetched.
    * ``200``: the server ignores ranges and sends the whole body. It is
      accepted only within ``max_bytes``.
    """
    log.info("Probing %s with a %s-byte suffix Range request", url, block_size)

    try:
        with safe_get(
            url,
            headers={"Range": f"bytes=-{block_size}"},
            timeout=timeout,
            stream=True,
        ) as resp:
            log.info(
                "%s answered %s (final URL %s, Content-Range %r, Content-Length %r)",
                url,
                resp.status_code,
                resp.url,
                resp.headers.get("content-range"),
                resp.headers.get("content-length"),
            )

            if resp.status_code == requests.codes.requested_range_not_satisfiable:
                return io.BytesIO(fetch_full(url, max_bytes, timeout))

            resp.raise_for_status()

            if resp.status_code != requests.codes.partial_content:
                log.warning(
                    "%s ignores Range requests; downloading the whole file", url
                )
                check_limit(
                    content_length(resp.headers.get("content-length")), max_bytes
                )
                return io.BytesIO(read_limited(resp, max_bytes))

            total = total_from_content_range(resp.headers.get("content-range"))

            if total is None:
                raise UnfoldError(tk._("The server returned an invalid Content-Range"))

            final_url = resp.url
            tail = read_limited(resp, max_bytes)
    except requests.RequestException as e:
        raise UnfoldError(
            tk._("Could not fetch remote archive: %(error)s") % {"error": e}
        ) from e

    if len(tail) >= total:
        return io.BytesIO(tail)

    # ``final_url`` is where the redirects ended (e.g. a signed storage URL);
    # reusing it saves a redirect round trip on every Range request.
    remote = RemoteRangeFile(
        final_url or url, total, max_bytes, block_size=block_size, timeout=timeout
    )
    remote.seed(total - len(tail), tail)
    remote.bytes_fetched = len(tail)
    remote.requests_made = 1

    return io.BufferedReader(remote, buffer_size=block_size)
