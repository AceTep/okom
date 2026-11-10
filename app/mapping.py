"""Map a screen or a gaze point to the window that should get focus."""

from __future__ import annotations

from app.backends.base import Screen, Window


def screen_of_active(screens: list[Screen], windows: list[Window]) -> int | None:
    """Index of the screen the active window is on, or None."""
    active = next((w for w in windows if w.active), None)
    if active is None:
        return None
    return next((s.index for s in screens if s.name == active.screen), None)


def focus_candidates(
    screens: list[Screen], windows: list[Window], screen_index: int
) -> list[Window]:
    """Windows on the given screen, topmost first; empty if nothing should change.

    Empty also when the active window is already on that screen, so a manual
    Alt+Tab within one screen is never undone. The caller tries them in order,
    so a window that refuses activation (e.g. a dialog that is closing) is
    skipped instead of leaving focus where it was.
    """
    screen = next((s for s in screens if s.index == screen_index), None)
    if screen is None:
        return []
    on_screen = [w for w in windows if w.screen == screen.name]
    if any(w.active for w in on_screen):
        return []
    return sorted(on_screen, key=lambda w: w.stack, reverse=True)


def focus_target(screens: list[Screen], windows: list[Window], screen_index: int) -> Window | None:
    """Topmost window on the given screen, or None if nothing should change."""
    candidates = focus_candidates(screens, windows, screen_index)
    return candidates[0] if candidates else None
