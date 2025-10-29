import ckan.plugins.toolkit as tk

CONF_CACHE_ENABLE = "ckanext.unfold.enable_cache"
CONF_MAX_FILE_SIZE = "ckanext.unfold.max_file_size"
CONF_ALLOWED_FORMATS = "ckanext.unfold.formats"


def is_cache_enabled() -> bool:
    """Check if caching is enabled in the configuration."""
    return tk.config[CONF_CACHE_ENABLE]


def get_max_file_size() -> int:
    return tk.config[CONF_MAX_FILE_SIZE]


def get_allowed_formats() -> list[str]:
    """Get the list of allowed archive formats from the configuration."""
    return tk.config[CONF_ALLOWED_FORMATS]
