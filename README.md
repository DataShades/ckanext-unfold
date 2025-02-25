[![Tests](https://github.com/DataShades/ckanext-unfold/actions/workflows/test.yml/badge.svg)](https://github.com/DataShades/ckanext-unfold/actions/workflows/test.yml)

# ckanext-unfold

Enhance your CKAN experience with our extension that enables seamless previews of various archive formats, ensuring easy access and efficient data management.

![Plugin presentation](doc/image.png)

## Supported Versions

CKAN >= 2.10

## Configuration

```ini
ckan.plugins = unfold
ckan.views.default_views = unfold_view
```

## What are the dependencies?

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
