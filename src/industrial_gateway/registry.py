from __future__ import annotations

from collections.abc import Iterable
from typing import Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def register(self, key: str, item: T) -> None:
        normalized = _normalize(key)
        if not normalized:
            raise ValueError("registry key is required")
        self._items[normalized] = item

    def get(self, key: str) -> T:
        normalized = _normalize(key)
        try:
            return self._items[normalized]
        except KeyError as exc:
            raise KeyError(f"unknown registry key: {key}") from exc

    def keys(self) -> list[str]:
        return sorted(self._items)

    def items(self) -> Iterable[tuple[str, T]]:
        return self._items.items()


def _normalize(key: str) -> str:
    return key.strip().lower()
