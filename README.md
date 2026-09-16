[![Tests](https://github.com/DataShades/ckanext-unfold/actions/workflows/test.yml/badge.svg)](https://github.com/DataShades/ckanext-unfold/actions/workflows/test.yml)

# ckanext-unfold

Enhance your CKAN experience with our extension that enables seamless previews of various archive formats, ensuring easy access and efficient data management.

![Plugin presentation](https://raw.githubusercontent.com/DataShades/ckanext-unfold/master/doc/view.png)

Features:
- Represents an archive as a file tree
- Supports the following archive formats: ZIP, ZIPX, JAR, RAR, CBR, 7Z, TAR, TAR.XZ, TAR.GZ, TAR.BZ2, DEB, RPM, A, AR, LIB
- Password-protected archives support for RAR format
- Caching the file tree for faster access
- File and folder search
- Support local and remote files
- Support for large archives

## Requirements

CKAN >= 2.11

Python >= 3.10

Redis (for caching)

Archives are only ever listed, never extracted, so RAR support needs no
`unrar`/`unar`/`bsdtar` binary on the host. A RAR archive with encrypted
filenames (not just encrypted file contents) is the one exception: listing
it needs a crypto backend, which the `cryptography` dependency provides
automatically.

## Configuration

```ini
ckan.plugins = unfold
ckan.views.default_views = unfold_view
```

### Settings

See the [config declaration](./ckanext/unfold/config_declaration.yaml) file.

## Large archives

The listing is built once per resource and cached in Redis as a folder index
(one hash per resource, one field per folder), for `ckanext.unfold.cache_ttl`
seconds. Staleness is checked on every read against a fingerprint of the
resource's `url`, `format`, `metadata_modified` and the view's `archive_pass`.

How the listing reaches the browser depends on `ckanext.unfold.expand_nodes_threshold`:

- **At most the threshold** (2000 entries by default): the whole tree is sent
  in one request and shown expanded.
- **Above it**: only the root folder is sent; each folder is requested when the
  user opens it, `ckanext.unfold.page_size` entries at a time with a
  "Show more" row for the rest. Search runs on the server and shows a flat
  list of the first 200 matching paths, since matches may sit in folders that
  are not loaded. The widget shows the total entry count and, for a search,
  how many entries matched. "Expand all" is disabled for these archives.

Remote ZIP archives are read through HTTP Range requests, so only the central
directory is transferred. A multi-gigabyte ZIP referenced by URL previews in a
few requests as long as the hosting server honours `Range`. Other formats are
downloaded in full and are subject to `ckanext.unfold.max_file_size`.

### API

- `get_archive_structure` (`id`, optional `view_id`, `parent`, `limit`):
  returns `{"mode": "full" | "lazy", "total": n, "nodes": [...]}`. In lazy
  mode `nodes` are the first `limit` direct children of `parent` (default
  `#`), with `children_total` and `has_more`. On failure returns
  `{"error": "..."}`.
- `search_archive_structure` (`id`, optional `view_id`, `q`, optional `limit`):
  returns `{"results": [{id, text, icon, is_dir, size, modified_at}, ...],
  "ids": [...folders to open...], "matches": n, "truncated": bool}`.

## Signals

The extension provides the following signals for customization and extension:
- `unfold:register_format_adapters`: Register custom adapters for specific file formats.
- `unfold:get_adapter_for_resource`: Get a custom adapter for a specific resource.

### Registering a custom adapter

You can register your own adapter for a specific file format by using the `unfold:register_format_adapters` signal.

In fact, it doesn't have to be an archive format — you can register an adapter for any file format that makes sense to be represented as a file tree. To create your own adapter, you need to inherit from `adapters.BaseAdapter` and implement the required methods.

We're providing a simple example adapter below. The node list generation is up to the developer.

```py
from ckanext.unfold.adapters import BaseAdapter
from ckanext.unfold.types import Node


class ExampleAdapter(BaseAdapter):
    def get_node_list(self) -> list[Node]:
        """Return list of nodes representing the archive structure.

        Ensure that your implementation handles both local and remote files:
        `self.is_upload` is `True` for a local upload and `False` for a
        remote URL.
        """
        return self.get_mock_node_list()

    def get_mock_node_list(self) -> list[Node]:
        return [
            Node(
                id="example_folder/",
                text="example_folder",
                icon="fa fa-folder",
                parent="#",
            ),
            Node(
                id="example_folder/example_file.txt",
                text="example_file.txt",
                icon="fa fa-file-text",
                parent="example_folder/",
                a_attr={
                    "href": "http://example.com/example_file.txt",
                    "target": "_blank",
                },
                data={
                    "type": "file",
                    "size": "50 KB",
                    "modified_at": "26/08/2021 - 20:13",
                },
            ),
            Node(
                id="example_folder/example_file.pdf",
                text="example_file.pdf",
                icon="fa fa-file-pdf",
                parent="example_folder/",
                data={
                    "type": "file",
                    "size": "1.2 MB",
                    "modified_at": "01/01/2024 - 00:00",
                },
            ),
            Node(
                id="another_file.docx",
                text="another_file.docx",
                icon="fa fa-file-word",
                parent="#",
                data={
                    "type": "file",
                    "size": "1.0 MB",
                    "modified_at": "01/01/2024 - 00:00",
                },
            ),
        ]
```

Then, you need to **register** your adapter using the signal. Each adapter registration function should accept a single argument: the adapter registry *instance* (not the class - the signal sends `ckanext.unfold.adapters.adapter_registry` itself, so mutating `adapters` here changes that shared registry).

```py
class ExamplePlugin(p.SingletonPlugin):
    ...

    p.implements(p.ISignal)

    # ISignal
    def get_signal_subscriptions(self) -> types.SignalMapping:
        return {
            tk.signals.ckanext.signal("unfold:register_format_adapters"): [
                self._register_format_adapters
            ],
        }

    @classmethod
    def _register_format_adapters(cls, adapters: unf_adapters.Registry) -> None:
        adapters.register("my.format", ExampleAdapter)
```

Each adapter is responsible for handling a specific file format. The key in the registry dictionary is the file format, and the value is the adapter class.

> [!NOTE]
> 1. You can register multiple adapters for different file formats.
> 2. This way, you can replace existing adapters by registering your own adapter for the same format.

The result preview will look like this:

![alt text](https://raw.githubusercontent.com/DataShades/ckanext-unfold/master/doc/example_adapter.png)

## Getting a custom adapter for a resource

Sometimes, you may want to provide a custom adapter for a specific resource based on some criteria, such as resource metadata or other attributes - or you may want to prevent certain resources from being previewed at all. You can do this by listening to the `unfold:get_adapter_for_resource` signal and returning the appropriate value when the criteria are met.

```py
...

from ckanext.unfold.utils import NO_PREVIEW, NoPreview


class ExamplePlugin(p.SingletonPlugin):
    ...

    p.implements(p.ISignal)

    # ISignal
    def get_signal_subscriptions(self) -> types.SignalMapping:
        return {
            tk.signals.ckanext.signal("unfold:get_adapter_for_resource"): [
                self._get_adapter_for_resource
            ],
        }

    @classmethod
    def _get_adapter_for_resource(
        cls, resource: dict[str, str]
    ) -> type[BaseAdapter] | None | bool | NoPreview:
        res_format = resource.get("format", "").lower()

        if res_format == "my.format":
            return ExampleAdapter

        if resource.get("private_notes"):
            return NO_PREVIEW

        return None
```

`get_adapter_for_resource_signal.send()` always calls every connected subscriber - blinker signals have no way to short-circuit that - so the following is about which result wins, not about skipping a call:

1. Return an adapter class if you want to provide a custom adapter for the resource. It wins outright: no later result or the default registry is consulted.
2. If you return `None`, this subscriber has no opinion: the next result (or, if none is left, the default registry lookup by the resource's `format`) decides instead.
3. Return `NO_PREVIEW` (`from ckanext.unfold.utils import NO_PREVIEW`) to force "never preview this resource". It wins outright like an adapter class does, except the resource gets no adapter at all - not even the default one for its format - so `can_view` reports `False`.
4. If you return `False`, no later result is consulted either - but unlike `NO_PREVIEW`, the default registry lookup by `format` **still runs afterwards**. This only suppresses a *later custom* adapter, not the built-in one for that format; it does not make the resource unpreviewable.

## Dependencies

Working with different archive formats requires different tools:

### RAR, CBR

It depends on `unrar` command-line utility to do the actual decompression. Note that by default it expect it to be in `PATH`.
If unrar launching fails, you need to fix this.

Alternatively, `rarfile` can also use either [unar](https://theunarchiver.com/command-line) from [TheUnarchiver](https://theunarchiver.com/) or
[bsdtar](https://github.com/libarchive/libarchive/wiki/ManPageBsdtar1) from [libarchive](https://www.libarchive.org/) as
decompression backend. From those unar is preferred as bsdtar has very limited support for RAR archives.

It depends on [cryptography](https://pypi.org/project/cryptography/) or [PyCryptodome](https://pypi.org/project/pycryptodome/)
modules to process archives with password-protected headers.

### 7Z

We are using [`py7zr`](https://py7zr.readthedocs.io/) library.

The py7zr depends on several external libraries. You should install these libraries with py7zr.
There are `PyCryptodome`, `PyZstd`, `PyPPMd`, `bcj-cffi`, `texttable`, and `multivolumefile`.
These packages are automatically installed when installing with pip command.

For extra information, please visit the [official documentation](https://py7zr.readthedocs.io/en/latest/user_guide.html#dependencies),
especially the dependencies section.

### ZIP, ZIPX, JAR

We are using built-in library [`zipfile`](https://docs.python.org/3/library/zipfile.html). Please consider referring to the official documentation for more information.

### TAR, TAR.XZ, TAR.GZ, TAR.BZ2

We are using built-in library [`tarfile`](https://docs.python.org/3/library/tarfile.html). Please consider referring to the official documentation for more information.

### RPM

We are using [`rpmfile`](https://github.com/srossross/rpmfile) library.

If you want to use rpmfile with zstd compressed rpms, you'll need to install the [`zstandard`](https://pypi.org/project/zstandard/) module.

### DEB, A, AR, LIB

We are using [`ar`](https://github.com/vidstige/ar) library. Please consider referring to the official documentation for more information.

## License

[AGPL](https://www.gnu.org/licenses/agpl-3.0.en.html)
