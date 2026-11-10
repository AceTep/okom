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


def test_candidates_topmost_first() -> None:
    from app.mapping import focus_candidates

    windows = [
        win("code", "HDMI-A-1", 6, active=True),
        win("chat", "eDP-1", 2),
        win("firefox", "eDP-1", 5),
    ]
    assert [w.id for w in focus_candidates(SCREENS, windows, 1)] == ["firefox", "chat"]
    assert focus_candidates(SCREENS, windows, 0) == []  # already focused there


def test_switch_falls_back_to_next_window() -> None:
    from app.backends.base import FocusBackend
    from app.main import switch_to
    from shared.protocol import GazeMessage

    class Backend(FocusBackend):
        def __init__(self) -> None:
            self.tried: list[str] = []

        def list_screens(self):
            return SCREENS

        def list_windows(self):
            return [
                win("code", "HDMI-A-1", 6, active=True),
                win("closing-dialog", "eDP-1", 9),
                win("firefox", "eDP-1", 5),
            ]

        def focus(self, window_id: str) -> bool:
            self.tried.append(window_id)
            return window_id != "closing-dialog"

    msg = GazeMessage(t=0.0, face=True, users=1, screen=1, x=0.5, y=0.5, conf=0.9, blink=False)
    backend = Backend()
    assert switch_to(backend, 1, msg) is True
    assert backend.tried == ["closing-dialog", "firefox"]
