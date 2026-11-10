"""Screen ordering shared by gaze/ and app/.

The protocol sends a screen index, so both sides must number screens the same
way. Rule: sort by the top-left corner in the global desktop layout, top to
bottom, then left to right (row-major reading order). Ties break by name.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")


def screen_sort_key(name: str, x: int, y: int) -> tuple[int, int, str]:
    return (y, x, name)


def order_screens(items: Iterable[T], key: Callable[[T], tuple[str, int, int]]) -> list[T]:
    """Return items in protocol order. `key` maps an item to (name, x, y)."""
    return sorted(items, key=lambda item: screen_sort_key(*key(item)))
