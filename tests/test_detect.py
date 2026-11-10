import pytest

from app.backends.base import FocusBackend, Rect, Screen, Window
from app.backends.detect import choose_backend, create_backend
from app.backends.dummy import DummyBackend


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("win32", {"XDG_CURRENT_DESKTOP": "KDE"}, "windows"),
        ("linux", {"HYPRLAND_INSTANCE_SIGNATURE": "abc", "SWAYSOCK": "/x"}, "hyprland"),
        ("linux", {"SWAYSOCK": "/run/sway.sock"}, "sway"),
        ("linux", {"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "KDE"}, "x11"),
        ("linux", {"DISPLAY": ":0"}, "x11"),
        ("linux", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"}, "kde_wayland"),
        (
            "linux",
            {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"},
            "gnome_wayland",
        ),
        (
            "linux",
            {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_CURRENT_DESKTOP": "KDE"},
            "kde_wayland",
        ),
        ("linux", {}, "dummy"),
        ("darwin", {}, "dummy"),
    ],
)
def test_choose_backend(platform: str, env: dict, expected: str) -> None:
    assert choose_backend(platform, env) == expected


class FakeBackend(FocusBackend):
    name = "fake"

    def __init__(self, windows: list[Window]) -> None:
        self._windows = windows

    def list_screens(self) -> list[Screen]:
        return []

    def list_windows(self) -> list[Window]:
        return self._windows

    def focus(self, window_id: str) -> bool:
        return True


KDE_ENV = {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"}
ONE_WINDOW = [Window("1", "t", Rect(0, 0, 10, 10), "eDP-1", 0, True)]


def test_create_uses_working_backend() -> None:
    backend = create_backend("linux", KDE_ENV, {"kde_wayland": lambda: FakeBackend(ONE_WINDOW)})
    assert isinstance(backend, FakeBackend)


def test_create_falls_back_when_no_windows() -> None:
    backend = create_backend("linux", KDE_ENV, {"kde_wayland": lambda: FakeBackend([])})
    assert isinstance(backend, DummyBackend)
    assert "no windows" in backend.reason


def test_create_falls_back_on_error() -> None:
    def broken() -> FocusBackend:
        raise RuntimeError("no dbus")

    backend = create_backend("linux", KDE_ENV, {"kde_wayland": broken})
    assert isinstance(backend, DummyBackend)
    assert "no dbus" in backend.reason


def test_create_falls_back_when_not_implemented() -> None:
    backend = create_backend("linux", {"SWAYSOCK": "/x"}, {})
    assert isinstance(backend, DummyBackend)
    assert "not implemented" in backend.reason
