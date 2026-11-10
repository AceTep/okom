"""Treat SIGTERM like Ctrl+C, so `kill` and the launcher's Stop clean up too."""

from __future__ import annotations

import signal


def _raise_keyboard_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


def sigterm_as_keyboard_interrupt() -> None:
    """Call once at start-up from the main thread."""
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
