from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolRegistry:
    _tools: dict[str, Callable[..., object]] = field(default_factory=dict)

    def register(self, name: str, fn: Callable[..., object]) -> None:
        self._tools[name] = fn

    def get(self, name: str) -> Callable[..., object] | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())
