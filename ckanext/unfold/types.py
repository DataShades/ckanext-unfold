from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Node(BaseModel):
    id: str
    text: str
    icon: str
    parent: str
    state: dict[str, bool] = Field(default={"opened": True})
    data: dict[str, Any] = Field(default_factory=dict)
