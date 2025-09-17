from __future__ import annotations

import random
from copy import deepcopy

import pytest

import ckanext.unfold.truncate as unf_truncate
import ckanext.unfold.types as unf_types


@pytest.mark.parametrize(
    "archive_size,max_size,expected",
    [
        (1000, 2000, True),
        (2000, 1000, False),
        (1000, None, True),
        (None, 1000, True),
    ],
)
def test_check_size_limit(archive_size, max_size, expected):
    result = unf_truncate.check_size_limit(archive_size, max_size)
    assert result == expected


def test_sort_nodes(complex_tree):
    before = deepcopy(complex_tree)
    random.shuffle(complex_tree)
    after = unf_truncate.sort_nodes(complex_tree)
    assert [a.id for a in after] == [b.id for b in before]


@pytest.mark.parametrize(
    "max_count,expect_truncation",
    [
        (5, True),
        (10, True),
        (20, True),
        (100, False),
        (None, False),
    ],
)
def test_max_count(complex_tree, max_count, expect_truncation):
    before = deepcopy(complex_tree)
    random.shuffle(complex_tree)
    truncated_nodes = unf_truncate.apply_all_truncations(
        complex_tree, max_count=max_count
    )
    if expect_truncation:
        assert len(truncated_nodes) == max_count


@pytest.mark.parametrize(
    "max_depth,expect_truncation",
    [
        (1, True),
        (2, True),
        (3, True),
        (5, False),
        (None, False),
    ],
)
def test_max_depth(complex_tree, max_depth, expect_truncation):
    before = deepcopy(complex_tree)
    random.shuffle(complex_tree)
    truncated_nodes = unf_truncate.apply_all_truncations(
        complex_tree, max_depth=max_depth
    )

    if expect_truncation:
        assert any(["__truncated__" in n.id for n in truncated_nodes])
    else:
        assert all(["__truncated__" not in n.id for n in truncated_nodes])


@pytest.mark.parametrize(
    "max_nested_count,expect_truncation",
    [
        (1, True),
        (4, True),
        (8, False),
        (10, False),
        (None, False),
    ],
)
def test_max_nested_count(complex_tree, max_nested_count, expect_truncation):
    before = deepcopy(complex_tree)
    random.shuffle(complex_tree)
    truncated_nodes = unf_truncate.apply_all_truncations(
        complex_tree, max_nested_count=max_nested_count
    )

    if expect_truncation:
        filtered = [n.id for n in truncated_nodes]
        assert any(["__truncated__" in _id for _id in filtered])


@pytest.mark.parametrize(
    "max_count, max_nested_count, max_depth, expect_truncation, expect_truncation_at_end",
    [(10, 5, 2, True, True), (15, 5, 2, True, True), (20, 5, 2, True, False)],
)
def test_mixed(
    complex_tree,
    max_count,
    max_nested_count,
    max_depth,
    expect_truncation,
    expect_truncation_at_end,
):
    before = deepcopy(complex_tree)
    random.shuffle(complex_tree)
    truncated_nodes = unf_truncate.apply_all_truncations(
        complex_tree,
        max_count=max_count,
        max_nested_count=max_nested_count,
        max_depth=max_depth,
    )

    if expect_truncation:
        filtered = [n.id for n in truncated_nodes]
        assert any(["__truncated__" in _id for _id in filtered])
    if expect_truncation_at_end:
        assert "__truncated__" in filtered[-1]
