"""Map a screen or a gaze point to the window that should get focus."""

from __future__ import annotations

from app.backends.base import Screen, Window


def screen_of_active(screens: list[Screen], windows: list[Window]) -> int | None:
    """Index of the screen the active window is on, or None."""
    active = next((w for w in windows if w.active), None)
    if active is None:
        return None
    return next((s.index for s in screens if s.name == active.screen), None)


def focus_target(screens: list[Screen], windows: list[Window], screen_index: int) -> Window | None:
    """Topmost window on the given screen, or None if nothing should change.

    None also when the active window is already on that screen, so a manual
    Alt+Tab within one screen is never undone.
    """
    screen = next((s for s in screens if s.index == screen_index), None)
    if screen is None:
        return None
    on_screen = [w for w in windows if w.screen == screen.name]
    if not on_screen or any(w.active for w in on_screen):
        return None
    return max(on_screen, key=lambda w: w.stack)
