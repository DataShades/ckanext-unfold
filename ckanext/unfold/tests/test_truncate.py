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


def test_complex_tree_generation(complex_tree):
    before = deepcopy(complex_tree)
    random.shuffle(complex_tree)
    after = unf_truncate.sort_nodes(complex_tree)
    assert [a.id for a in after] == [b.id for b in before]
