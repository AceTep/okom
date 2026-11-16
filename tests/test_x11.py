import pytest

from app.backends.base import Rect, Screen
from app.backends.x11 import assign_screen, focus_point, resolve_focus_method

SCREENS = [
    Screen(0, "DP-0", Rect(0, 251, 2560, 1440)),
    Screen(1, "DP-2", Rect(2560, 0, 3840, 2160)),
]


@pytest.mark.parametrize(
    ("configured", "wm", "expected"),
    [
        ("auto", "dwm", "pointer"),
        ("auto", "DWM", "pointer"),
        ("auto", "KWin", "ewmh"),
        ("auto", "", "ewmh"),
        ("ewmh", "dwm", "ewmh"),
        ("pointer", "i3", "pointer"),
    ],
)
def test_resolve_focus_method(configured: str, wm: str, expected: str) -> None:
    assert resolve_focus_method(configured, wm) == expected


def test_resolve_rejects_unknown_method() -> None:
    with pytest.raises(ValueError):
        resolve_focus_method("hotkey", "dwm")


@pytest.mark.parametrize(
    ("rect", "expected"),
    [
        (Rect(10, 260, 1200, 800), "DP-0"),
        (Rect(2570, 30, 1900, 2100), "DP-2"),
        # straddles both monitors: the larger part wins
        (Rect(2000, 300, 1000, 500), "DP-0"),
        (Rect(2400, 300, 1000, 500), "DP-2"),
        # dwm parks windows of hidden tags far to the left of every screen
        (Rect(-2400, 300, 1200, 800), None),
    ],
)
def test_assign_screen(rect: Rect, expected: str | None) -> None:
    assert assign_screen(rect, SCREENS) == expected


def test_assign_screen_without_screens() -> None:
    assert assign_screen(Rect(0, 0, 10, 10), []) is None


def test_focus_point_is_inside_window() -> None:
    rect = Rect(100, 50, 801, 601)
    x, y = focus_point(rect)
    assert (x, y) == (500, 350) and rect.contains(x, y)
