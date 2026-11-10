"""Decide when gaze has settled on another screen.

Pure logic, no I/O: time comes from the message timestamps, so it can be
tested without a camera, a network or windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import DecisionConfig
from shared.protocol import GazeMessage


@dataclass
class ScreenDecider:
    cfg: DecisionConfig
    current: int | None = None  # screen that currently has focus, if known
    _candidate: int | None = None
    _since: float = 0.0
    _last_usable: float | None = None
    _last_switch: float | None = None

    def set_current(self, screen: int | None) -> bool:
        """Focus moved to `screen` outside of this decider (click, Alt+Tab, our own switch).

        Returns True if that changed what the decider believed. A dwell towards
        the screen that now has focus is pointless, so it is dropped.
        """
        if screen == self.current:
            return False
        self.current = screen
        if self._candidate == screen:
            self._candidate = None
        return True

    def usable(self, msg: GazeMessage) -> bool:
        """Blinks, lost faces, unsure screens and low confidence are skipped."""
        return (
            msg.face and not msg.blink and msg.screen is not None and msg.conf >= self.cfg.min_conf
        )

    def update(self, msg: GazeMessage) -> int | None:
        """Feed one message. Returns a screen index exactly when focus should move there."""
        if not self.usable(msg):
            return None  # skipped: neither advances nor resets the dwell
        t = msg.t
        if self._last_usable is not None and t - self._last_usable > self.cfg.max_gap_s:
            self._candidate = None
        self._last_usable = t

        if msg.screen == self.current:
            self._candidate = None
            return None
        if msg.screen != self._candidate:
            self._candidate = msg.screen
            self._since = t
        if t - self._since < self.cfg.dwell_s:
            return None
        if self._last_switch is not None and t - self._last_switch < self.cfg.cooldown_s:
            return None
        self.current = self._candidate
        self._candidate = None
        self._last_switch = t
        return self.current
