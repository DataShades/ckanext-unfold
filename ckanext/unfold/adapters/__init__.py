from ckanext.unfold import types as unf_types
from ckanext.unfold.adapters import _7z, ar, rar, rpm, tar, zip
from ckanext.unfold.adapters.base import BaseAdapter
from ckanext.unfold.types import Registry

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "rar": rar.RarAdapter,
    "cbr": rar.RarAdapter,
    "7z": _7z.SevenZipAdapter,
    "zip": zip.ZipAdapter,
    "zipx": zip.ZipAdapter,
    "jar": zip.ZipAdapter,
    "tar": tar.TarAdapter,
    "tar.gz": tar.TarGzAdapter,
    "tar.xz": tar.TarXzAdapter,
    "tar.bz2": tar.TarBz2Adapter,
    "rpm": rpm.RpmAdapter,
    "deb": ar.ArAdapter,
    "ar": ar.ArAdapter,
    "a": ar.ArAdapter,
    "lib": ar.ArAdapter,
}

adapter_registry: unf_types.Registry[str, type[BaseAdapter]] = Registry(ADAPTERS)

__all__ = ["adapter_registry", "BaseAdapter", "ADAPTERS", "Registry"]
