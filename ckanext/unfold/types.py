from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass
class Node:
    id: str
    text: str
    icon: str
    parent: str
    state: dict[str, bool] = field(default_factory=lambda: {"opened": True})
    data: dict[str, Any] = field(default_factory=dict)
    li_attr: dict[str, str] | None = None
    a_attr: dict[str, str] | None = field(default_factory=lambda: {"tabindex": "0"})
    children: bool = False


class Registry(dict[K, V], Generic[K, V]):
    """A generic registry to store and retrieve items."""

    def reset(self):
        self.clear()

    def register(self, name: K, member: V) -> None:
        self[name] = member
