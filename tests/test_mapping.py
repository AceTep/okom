from app.backends.base import Rect, Screen, Window
from app.mapping import focus_target, screen_of_active

SCREENS = [
    Screen(0, "HDMI-A-1", Rect(0, 0, 1920, 1080)),
    Screen(1, "eDP-1", Rect(0, 1080, 1920, 1080)),
]


def win(id: str, screen: str, stack: int, active: bool = False) -> Window:
    return Window(id, id, Rect(0, 0, 100, 100), screen, stack, active)


def test_topmost_window_on_target_screen() -> None:
    windows = [
        win("code", "HDMI-A-1", 6, active=True),
        win("firefox", "eDP-1", 5),
        win("chat", "eDP-1", 2),
    ]
    assert focus_target(SCREENS, windows, 1).id == "firefox"


def test_nothing_when_active_window_already_on_target() -> None:
    windows = [win("code", "HDMI-A-1", 6), win("firefox", "eDP-1", 5, active=True)]
    assert focus_target(SCREENS, windows, 1) is None


def test_nothing_when_screen_empty() -> None:
    windows = [win("code", "HDMI-A-1", 6, active=True)]
    assert focus_target(SCREENS, windows, 1) is None


def test_unknown_screen_index() -> None:
    assert focus_target(SCREENS, [win("a", "eDP-1", 1)], 7) is None


def test_screen_of_active() -> None:
    windows = [win("code", "HDMI-A-1", 6), win("firefox", "eDP-1", 5, active=True)]
    assert screen_of_active(SCREENS, windows) == 1
    assert screen_of_active(SCREENS, [win("code", "HDMI-A-1", 6)]) is None
