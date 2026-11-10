"""Fallback backend: sees no real windows and only logs focus requests."""

from __future__ import annotations

import logging

from app.backends.base import FocusBackend, Rect, Screen, Window

log = logging.getLogger(__name__)


class DummyBackend(FocusBackend):
    name = "dummy"

    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        self.focused: list[str] = []

    def list_screens(self) -> list[Screen]:
        return [Screen(0, "dummy", Rect(0, 0, 1920, 1080))]

    def list_windows(self) -> list[Window]:
        return []

    def focus(self, window_id: str) -> bool:
        log.info("[dummy] would focus %s", window_id)
        self.focused.append(window_id)
        return True
