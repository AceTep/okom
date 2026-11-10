"""Fullscreen guide on every screen: shows where to look and when.

The screen to look at gets a lit background, an accent border, a countdown
in the corner and a dot that walks over the calibration points. All other
screens go dark. Esc or Ctrl+C aborts.
"""

from __future__ import annotations

import logging
import math
import signal
import time
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeyEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QApplication, QWidget

from gaze.targets import Countdown, Step, Target, step_at
from shared.screens import order_screens

log = logging.getLogger(__name__)

ACCENT = QColor(80, 160, 255)
ACTIVE_BG = QColor(26, 28, 36)
IDLE_BG = QColor(0, 0, 0)
TEXT = QColor(230, 230, 235)
DIM_TEXT = QColor(90, 90, 100)
BORDER_PX = 8
DOT_PX = 10
RING_START_PX = 44  # ring shrinks from this to DOT_PX while the eyes settle


def ordered_qt_screens() -> list:
    """Qt screens in protocol order (same rule as app/, see shared/screens.py)."""
    return order_screens(
        QGuiApplication.screens(), key=lambda s: (s.name(), s.geometry().x(), s.geometry().y())
    )


class ScreenWindow(QWidget):
    def __init__(self, index: int, on_abort: Callable[[], None]) -> None:
        super().__init__()
        self.index = index
        self.step: Step | None = None
        self._on_abort = on_abort
        self.setWindowTitle(f"okom calibration {index}")
        self.setCursor(Qt.CursorShape.BlankCursor)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            self._on_abort()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        step, now = self.step, time.time()
        if step is None or step.screen != self.index:
            p.fillRect(self.rect(), IDLE_BG)
            text = "Get ready" if step is None else f"Look at screen {step.screen}"
            self._text(p, self.rect(), text, 22, DIM_TEXT, Qt.AlignmentFlag.AlignCenter)
            return

        p.fillRect(self.rect(), ACTIVE_BG)
        p.setPen(QPen(ACCENT, BORDER_PX))
        half = BORDER_PX / 2
        p.drawRect(QRectF(half, half, self.width() - BORDER_PX, self.height() - BORDER_PX))
        corner = QRectF(48, 40, self.width() - 96, 160)
        top_left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop

        if isinstance(step, Countdown):
            left = max(1, math.ceil(step.end - now))
            self._text(p, corner, f"{left}", 72, TEXT, top_left)
            below = corner.translated(0, 100)
            self._text(p, below, "Look at this screen, follow the dot", 22, TEXT, top_left)
            self._dot(p, step.first_x, step.first_y, RING_START_PX, solid=False)
            return

        assert isinstance(step, Target)
        self._text(p, corner, f"Point {step.number}/{step.total}", 20, DIM_TEXT, top_left)
        if now < step.record_from:  # eyes are moving there: shrinking ring
            k = (now - step.start) / max(step.record_from - step.start, 1e-6)
            self._dot(p, step.x, step.y, RING_START_PX + (DOT_PX - RING_START_PX) * k, solid=False)
        else:
            self._dot(p, step.x, step.y, DOT_PX, solid=True)

    def _dot(self, p: QPainter, x: float, y: float, radius: float, solid: bool) -> None:
        centre = QPointF(x * self.width(), y * self.height())
        p.setPen(QPen(ACCENT, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(centre, radius, radius)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(TEXT if solid else ACCENT)
        p.drawEllipse(centre, 3.0, 3.0)
        if solid:
            p.drawEllipse(centre, DOT_PX - 3.0, DOT_PX - 3.0)

    @staticmethod
    def _text(p: QPainter, rect, text: str, size: int, color: QColor, align) -> None:
        font = QFont()
        font.setPixelSize(size)
        p.setFont(font)
        p.setPen(color)
        p.drawText(rect, align, text)


def run_overlay(
    app: QApplication,
    timeline: list[Step],
    should_stop: Callable[[], bool] = lambda: False,
) -> bool:
    """Show the timeline on all screens. Returns True if it ran to the end."""
    state = {"aborted": False, "stop_requested": False}

    def abort() -> None:
        state["aborted"] = True
        app.quit()

    windows = []
    for i, screen in enumerate(ordered_qt_screens()):
        w = ScreenWindow(i, abort)
        w.setScreen(screen)
        w.setGeometry(screen.geometry())
        w.showFullScreen()
        windows.append(w)

    end = timeline[-1].end

    def tick() -> None:
        if state["stop_requested"]:
            abort()
            return
        if should_stop():
            log.error("stopping the overlay: the capture thread reported a problem")
            abort()
            return
        now = time.time()
        if now >= end:
            app.quit()
            return
        step = step_at(timeline, now)
        for w in windows:
            w.step = step
            w.update()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(16)

    # Ctrl+C and SIGTERM abort cleanly. The handler only sets a flag: Python runs
    # it between any two bytecodes, also in the middle of paintEvent, and quitting
    # Qt from there crashed Qt's Wayland code (measured: 3 of 16 runs). The timer
    # tick, outside any painting, does the actual abort.
    def request_stop(*_: object) -> None:
        state["stop_requested"] = True

    stop_signals = (signal.SIGINT, signal.SIGTERM)
    previous = {sig: signal.signal(sig, request_stop) for sig in stop_signals}
    try:
        app.exec()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        timer.stop()
        for w in windows:
            w.close()
    return not state["aborted"]
