from __future__ import annotations

import random
from copy import deepcopy

import pytest

import ckanext.unfold.truncate as unf_truncate
import ckanext.unfold.types as unf_types
import ckanext.unfold.utils as unf_utils


@pytest.mark.parametrize(
    ("archive_size", "max_size", "expected"),
    [
        (1000, 2000, True),
        (2000, 1000, False),
        (1000, None, True),
        (None, 1000, True),
    ],
)
def test_check_size_limit(
    archive_size: int | None, max_size: int | None, expected: bool
):
    assert unf_utils.check_size_limit(archive_size, max_size) == expected


def test_sort_nodes(complex_tree: list[unf_types.Node]):
    before = deepcopy(complex_tree)
    random.shuffle(complex_tree)
    after = unf_truncate.sort_nodes(complex_tree)
    assert [a.id for a in after] == [b.id for b in before]


@pytest.mark.parametrize(
    ("max_total", "expect_truncation"),
    [
        (5, True),
        (10, True),
        (20, True),
        (100, False),
    ],
)
def test_max_total(
    complex_tree: list[unf_types.Node], max_total: int, expect_truncation: bool
):
    random.shuffle(complex_tree)
    truncated_nodes = unf_truncate.truncate_nodes(complex_tree, max_total=max_total)

    if expect_truncation:
        assert len(truncated_nodes) in [
            max_total,
            max_total + 1,
        ]  # empty folders are not allowed an additional nodecould be added.


@pytest.mark.parametrize(
    ("max_depth", "expect_truncation"),
    [
        (1, True),
        (2, True),
        (3, True),
        (5, False),
        (None, False),
    ],
)
def test_max_depth(
    complex_tree: list[unf_types.Node], max_depth: int | None, expect_truncation: bool
):
    random.shuffle(complex_tree)

    truncated_nodes = unf_truncate.truncate_nodes(complex_tree, max_depth=max_depth)

    if expect_truncation:
        assert any(["__truncated__" in n.id for n in truncated_nodes])
    else:
        assert all(["__truncated__" not in n.id for n in truncated_nodes])


@pytest.mark.parametrize(
    ("max_nested", "expect_truncation"),
    [
        (1, True),
        (4, True),
        (8, False),
        (10, False),
        (None, False),
    ],
)
def test_max_nested(complex_tree, max_nested, expect_truncation):
    random.shuffle(complex_tree)
    truncated_nodes = unf_truncate.truncate_nodes(complex_tree, max_nested=max_nested)

    if expect_truncation:
        filtered = [n.id for n in truncated_nodes]
        assert any(["__truncated__" in _id for _id in filtered])


@pytest.mark.parametrize(
    (
        "max_total",
        "max_nested",
        "max_depth",
        "expect_truncation",
        "expect_truncation_at_end",
    ),
    [(10, 5, 2, True, True), (15, 5, 2, True, True), (20, 5, 2, True, False)],
)
def test_mixed(
    complex_tree: list[unf_types.Node],
    max_total: int,
    max_nested: int,
    max_depth: int | None,
    expect_truncation: bool,
    expect_truncation_at_end: bool,
):
    random.shuffle(complex_tree)
    truncated_nodes = unf_truncate.truncate_nodes(
        complex_tree,
        max_total=max_total,
        max_nested=max_nested,
        max_depth=max_depth,
    )

    if expect_truncation:
        filtered = [n.id for n in truncated_nodes]
        assert any(["__truncated__" in _id for _id in filtered])
    if expect_truncation_at_end:
        assert "__truncated__" in filtered[-1]
