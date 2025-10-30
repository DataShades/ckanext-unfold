import ckan.plugins.toolkit as tk

CONF_CACHE_ENABLE = "ckanext.unfold.enable_cache"
CONF_MAX_FILE_SIZE = "ckanext.unfold.max_file_size"
CONF_EXPAND_NODES_THRESHOLD = "ckanext.unfold.expand_nodes_threshold"


def is_cache_enabled() -> bool:
    """Check if caching is enabled in the configuration."""
    return tk.config[CONF_CACHE_ENABLE]


def get_max_file_size() -> int:
    return tk.config[CONF_MAX_FILE_SIZE]


def get_expand_nodes_threshold() -> int:
    """Get the threshold for expanding nodes in the UI tree view."""
    return tk.config[CONF_EXPAND_NODES_THRESHOLD]
