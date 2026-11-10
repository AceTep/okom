"""Common interface for platform focus backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from shared.screens import order_screens


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    def area_overlap(self, other: Rect) -> int:
        dx = min(self.x + self.w, other.x + other.w) - max(self.x, other.x)
        dy = min(self.y + self.h, other.y + other.h) - max(self.y, other.y)
        return max(dx, 0) * max(dy, 0)


@dataclass(frozen=True, slots=True)
class Screen:
    index: int  # protocol index, see shared/screens.py
    name: str  # output name, e.g. "eDP-1"
    rect: Rect  # logical pixels in the global layout


@dataclass(frozen=True, slots=True)
class Window:
    id: str
    title: str
    rect: Rect
    screen: str  # output name the compositor assigns the window to
    stack: int  # stacking position, higher is closer to the top
    active: bool


def index_screens(named: list[tuple[str, Rect]]) -> list[Screen]:
    """Assign protocol indices to (name, rect) pairs."""
    ordered = order_screens(named, key=lambda s: (s[0], s[1].x, s[1].y))
    return [Screen(i, name, rect) for i, (name, rect) in enumerate(ordered)]


class CursorStream(ABC):
    """Live mouse position in global logical pixels (used by app.mock_gaze)."""

    @abstractmethod
    def latest(self) -> tuple[int, int] | None:
        """Most recent position, or None if none has arrived yet. Never blocks."""

    @abstractmethod
    def close(self) -> None:
        """Stop the stream."""


class FocusBackend(ABC):
    name: str = "base"

    @abstractmethod
    def list_screens(self) -> list[Screen]:
        """Screens in protocol order."""

    @abstractmethod
    def list_windows(self) -> list[Window]:
        """Normal, visible windows on the current desktop."""

    @abstractmethod
    def focus(self, window_id: str) -> bool:
        """Give keyboard focus to a window. Returns True on success."""

    def snapshot(self) -> tuple[list[Screen], list[Window]]:
        """Screens and windows together; backends may do this in one query."""
        return self.list_screens(), self.list_windows()

    def start_highlight(self) -> bool:
        """Make the focused window stand out. Returns False if the platform cannot."""
        return False

    def stop_highlight(self) -> None:  # noqa: B027 - optional hook
        """Undo start_highlight(), leaving the desktop as it was before."""

    def open_cursor_stream(self, interval_ms: int = 33) -> CursorStream | None:
        """Mouse position stream, or None if the platform does not support it."""
        return None

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources."""
