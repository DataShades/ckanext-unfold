from __future__ import annotations

import pytest

import ckanext.unfold.config as unf_config
import ckanext.unfold.exception as unf_exception


@pytest.mark.parametrize("size_str,expected", [
    # Valid sizes
    ("50MB", 50 * 1024 ** 2),
    ("1GB", 1024 ** 3),
    ("500KB", 500 * 1024),
    ("1024B", 1024),
    ("2.5GB", int(2.5 * 1024 ** 3)),
    ("10.5MB", int(10.5 * 1024 ** 2)),
    # Case insensitive
    ("50mb", 50 * 1024 ** 2),
    ("1gb", 1024 ** 3),
    ("500Kb", 500 * 1024),
    ("1024b", 1024),
    # With whitespace
    ("  50MB  ", 50 * 1024 ** 2),
    ("1 GB", 1024 ** 3),
    ("500 KB", 500 * 1024),
    # None/empty cases
    (None, None),
    ("", None),
    ("   ", None),
])
def test_parse_size_config_valid(size_str, expected):
    """Test parsing valid size configurations."""
    result = unf_config.parse_size_config(size_str)
    assert result == expected


@pytest.mark.parametrize("size_str,error_msg", [
    # Invalid formats
    ("50", "Invalid size format"),
    ("MB50", "Invalid size format"),
    ("50TB", "Invalid size format"),  # Unsupported unit
    ("50XB", "Invalid size format"),  # Invalid unit
    ("invalid", "Invalid size format"),
    ("50 50 MB", "Invalid size format"),
    # Invalid numbers
    ("abc MB", "Invalid size format"),
    ("-50MB", "Invalid size format"),  # Negative not allowed by regex
    ("50.5.5MB", "Invalid size format"),  # Multiple decimals
])
def test_parse_size_config_invalid(size_str, error_msg):
    """Test parsing invalid size configurations."""
    with pytest.raises(unf_exception.UnfoldError, match=error_msg):
        unf_config.parse_size_config(size_str)


@pytest.mark.parametrize("value,expected", [
    # Valid depths
    ("5", 5),
    ("1", 1),
    ("100", 100),
    ("999", 999),
    # None/empty cases
    (None, None),
    ("", None),
])
def test_parse_max_depth_valid(value, expected):
    """Test parsing valid max depth values."""
    result = unf_config.parse_max_depth(value)
    assert result == expected


@pytest.mark.parametrize("value,error_msg", [
    # Invalid values
    ("0", "Max depth must be >= 1"),
    ("-1", "Max depth must be >= 1"),
    ("-5", "Max depth must be >= 1"),
    ("abc", "Invalid max_depth config"),
    ("5.5", "Invalid max_depth config"),
    ("1 2", "Invalid max_depth config"),
])
def test_parse_max_depth_invalid(value, error_msg):
    """Test parsing invalid max depth values."""
    with pytest.raises(unf_exception.UnfoldError, match=error_msg):
        unf_config.parse_max_depth(value)


@pytest.mark.parametrize("value,expected", [
    # Valid counts
    ("10", 10),
    ("1", 1),
    ("1000", 1000),
    ("50", 50),
    # None/empty cases
    (None, None),
    ("", None),
])
def test_parse_max_nested_count_valid(value, expected):
    """Test parsing valid max nested count values."""
    result = unf_config.parse_max_nested_count(value)
    assert result == expected


@pytest.mark.parametrize("value,error_msg", [
    # Invalid values
    ("0", "Max nested count must be >= 1"),
    ("-1", "Max nested count must be >= 1"),
    ("-10", "Max nested count must be >= 1"),
    ("abc", "Invalid max_nested_count config"),
    ("10.5", "Invalid max_nested_count config"),
    ("5 10", "Invalid max_nested_count config"),
])
def test_parse_max_nested_count_invalid(value, error_msg):
    """Test parsing invalid max nested count values."""
    with pytest.raises(unf_exception.UnfoldError, match=error_msg):
        unf_config.parse_max_nested_count(value)


@pytest.mark.parametrize("value,expected", [
    # Valid counts
    ("1000", 1000),
    ("1", 1),
    ("5000", 5000),
    ("100", 100),
    # None/empty cases
    (None, None),
    ("", None),
])
def test_parse_max_count_valid(value, expected):
    """Test parsing valid max count values."""
    result = unf_config.parse_max_count(value)
    assert result == expected


@pytest.mark.parametrize("value,error_msg", [
    # Invalid values
    ("0", "Max count must be >= 1"),
    ("-1", "Max count must be >= 1"),
    ("-100", "Max count must be >= 1"),
    ("abc", "Invalid max_count config"),
    ("1000.5", "Invalid max_count config"),
    ("100 200", "Invalid max_count config"),
])
def test_parse_max_count_invalid(value, error_msg):
    """Test parsing invalid max count values."""
    with pytest.raises(unf_exception.UnfoldError, match=error_msg):
        unf_config.parse_max_count(value)


@pytest.mark.parametrize("value,supported_formats,expected", [
    # Valid format lists
    ("zip tar 7z", ["zip", "tar", "7z", "rar"], ["zip", "tar", "7z"]),
    ("ZIP TAR", ["zip", "tar", "7z", "rar"], ["zip", "tar"]),  # Case insensitive
    ("  zip   tar  7z  ", ["zip", "tar", "7z", "rar"], ["zip", "tar", "7z"]),  # Extra whitespace
    ("rar", ["zip", "tar", "7z", "rar"], ["rar"]),  # Single format
    ("zip tar rar 7z", ["zip", "tar", "7z", "rar"], ["zip", "tar", "rar", "7z"]),
    # None/empty cases should return all supported formats
    (None, ["zip", "tar", "7z", "rar"], ["zip", "tar", "7z", "rar"]),
    ("", ["zip", "tar", "7z", "rar"], ["zip", "tar", "7z", "rar"]),
    ("   ", ["zip", "tar", "7z", "rar"], ["zip", "tar", "7z", "rar"]),
])
def test_parse_formats_valid(value, supported_formats, expected):
    """Test parsing valid format configurations."""
    result = unf_config.parse_formats(value, supported_formats)
    assert result == expected


def test_parse_formats_unsupported_formats(caplog):
    """Test handling of unsupported formats in configuration."""
    supported_formats = ["zip", "tar", "7z"]
    value = "zip tar unsupported_format another_unsupported"
    
    result = unf_config.parse_formats(value, supported_formats)
    
    # Should only return supported formats
    assert result == ["zip", "tar"]
    
    # Should log warning about unsupported formats
    assert "unsupported_format" in caplog.text
    assert "another_unsupported" in caplog.text


def test_parse_formats_all_unsupported():
    """Test configuration with all unsupported formats."""
    supported_formats = ["zip", "tar"]
    value = "unsupported1 unsupported2"
    
    result = unf_config.parse_formats(value, supported_formats)
    
    # Should return empty list when no formats are supported
    assert result == []