from __future__ import annotations

from collections.abc import Hashable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class Node(BaseModel):
    id: str
    text: str
    icon: str
    parent: str
    state: dict[str, bool] = Field(default={"opened": False})
    data: dict[str, Any] = Field(default_factory=dict)
    li_attr : dict[str, str] | None = None
    a_attr: dict[str, str] | None = None
    children: bool = False


class Registry(dict[K, V], Generic[K, V]):
    """A generic registry to store and retrieve items."""

    def reset(self):
        self.clear()

    def register(self, name: K, member: V) -> None:
        self[name] = member
