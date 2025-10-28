import ckan.plugins.toolkit as tk

CONF_CACHE_ENABLE = "ckanext.unfold.enable_cache"
CONF_MAX_DEPTH = "ckanext.unfold.max_depth"
CONF_MAX_TOTAL = "ckanext.unfold.max_total"
CONF_MAX_NESTED_COUNT = "ckanext.unfold.max_nested_count"
CONF_MAX_SIZE = "ckanext.unfold.max_size"
CONF_ALLOWED_FORMATS = "ckanext.unfold.formats"


def is_cache_enabled() -> bool:
    """Check if caching is enabled in the configuration."""
    return tk.config[CONF_CACHE_ENABLE]


def get_max_depth() -> int:
    return tk.config[CONF_MAX_DEPTH]


def get_max_total() -> int:
    return tk.config[CONF_MAX_TOTAL]


def get_max_nested_count() -> int:
    return tk.config[CONF_MAX_NESTED_COUNT]


def get_max_size() -> int:
    return tk.config[CONF_MAX_SIZE]


def get_allowed_formats() -> list[str]:
    """Get the list of allowed archive formats from the configuration."""
    return tk.config[CONF_ALLOWED_FORMATS]
