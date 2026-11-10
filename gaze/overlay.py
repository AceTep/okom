"""Fullscreen guide on every screen: shows where to look and when.

The screen to look at gets a lit background, an accent border, a countdown
in the corner and a dot that walks over the calibration points. Every other
screen goes dark with a large arrow towards the right one, so looking at the
wrong screen is obvious. When the camera loses the face, or an earlier
calibration says the user looks at the wrong screen, the dot waits until it
is fixed. Esc or Ctrl+C aborts.
"""

from __future__ import annotations

import logging
import math
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeyEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QApplication, QWidget

from gaze.targets import (
    Countdown,
    Interval,
    PlaybackClock,
    Step,
    Target,
    WrongScreenDetector,
    direction,
    step_at,
)
from shared.screens import order_screens

log = logging.getLogger(__name__)

ACCENT = QColor(80, 160, 255)
ACTIVE_BG = QColor(26, 28, 36)
IDLE_BG = QColor(0, 0, 0)
TEXT = QColor(230, 230, 235)
DIM_TEXT = QColor(90, 90, 100)
WARNING = QColor(255, 90, 80)
FACE_WARNING = "Can't see your face\nFace the camera and check the light"
BORDER_PX = 8
DOT_PX = 10
RING_START_PX = 44  # ring shrinks from this to DOT_PX while the eyes settle


def ordered_qt_screens() -> list:
    """Qt screens in protocol order (same rule as app/, see shared/screens.py)."""
    return order_screens(
        QGuiApplication.screens(), key=lambda s: (s.name(), s.geometry().x(), s.geometry().y())
    )


class ScreenWindow(QWidget):
    def __init__(
        self, index: int, arrows: dict[int, tuple[str, str]], on_abort: Callable[[], None]
    ) -> None:
        super().__init__()
        self.index = index
        self.arrows = arrows  # target screen -> (arrow, word) pointing there from this one
        self.step: Step | None = None
        self.now = 0.0  # timeline time (stands still while paused)
        self.face_missing = False
        self.wrong_here = False  # the user looks at this screen but should not
        self.paused = False
        self._on_abort = on_abort
        self.setWindowTitle(f"okom calibration {index}")
        self.setCursor(Qt.CursorShape.BlankCursor)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape:
            self._on_abort()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        step = self.step
        if step is None or step.screen != self.index:
            self._paint_other(p, step)
        else:
            self._paint_active(p, step)
        p.end()

    def _paint_other(self, p: QPainter, step: Step | None) -> None:
        """Not the screen to look at: dark, with a big arrow to the right one."""
        p.fillRect(self.rect(), IDLE_BG)
        centre = Qt.AlignmentFlag.AlignCenter
        if step is None:
            self._text(p, self.rect(), "Get ready", 32, DIM_TEXT, centre)
            return
        arrow, word = self.arrows.get(step.screen, ("", f"screen {step.screen}"))
        color = WARNING if self.wrong_here or self.face_missing else TEXT
        h = self.height()
        self._text(p, QRectF(0, h * 0.18, self.width(), h * 0.35), arrow, 200, color, centre)
        self._text(
            p,
            QRectF(0, h * 0.55, self.width(), 70),
            f"Look at the screen {word}",
            44,
            color,
            centre,
        )
        if self.wrong_here:
            below = QRectF(0, h * 0.55 + 80, self.width(), 60)
            self._text(
                p,
                below,
                "You are looking at this screen. The dot waits for you.",
                26,
                color,
                centre,
            )
        if self.wrong_here or self.face_missing:
            self._border(p, WARNING)

    def _paint_active(self, p: QPainter, step: Step) -> None:
        p.fillRect(self.rect(), ACTIVE_BG)
        problem = self.face_missing or self.paused
        self._border(p, WARNING if problem else ACCENT)
        # Text goes between the rows of points (0.08 / 0.5 / 0.92 of the height), so it
        # never covers a dot: info between the top and middle row, warnings below middle.
        info = QRectF(48, self.height() * 0.2, self.width() - 96, 200)
        top_centre = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        middle = QRectF(48, self.height() * 0.6, self.width() - 96, 160)
        if self.face_missing:
            self._text(p, middle, FACE_WARNING, 40, WARNING, Qt.AlignmentFlag.AlignCenter)
        elif self.paused:
            self._text(
                p, middle, "Paused: look at this screen", 40, WARNING, Qt.AlignmentFlag.AlignCenter
            )

        if isinstance(step, Countdown):
            left = max(1, math.ceil(step.end - self.now))
            self._text(p, info, f"{left}", 72, TEXT, top_centre)
            below = info.translated(0, 100)
            self._text(p, below, "Look at this screen, follow the dot", 26, TEXT, top_centre)
            self._dot(p, step.first_x, step.first_y, RING_START_PX, solid=False)
            return

        assert isinstance(step, Target)
        self._text(p, info, f"Point {step.number}/{step.total}", 20, DIM_TEXT, top_centre)
        if self.now < step.record_from:  # eyes are moving there: shrinking ring
            k = (self.now - step.start) / max(step.record_from - step.start, 1e-6)
            self._dot(p, step.x, step.y, RING_START_PX + (DOT_PX - RING_START_PX) * k, solid=False)
        else:
            self._dot(p, step.x, step.y, DOT_PX, solid=True)

    def _border(self, p: QPainter, color: QColor) -> None:
        p.setPen(QPen(color, BORDER_PX))
        p.setBrush(Qt.BrushStyle.NoBrush)
        half = BORDER_PX / 2
        p.drawRect(QRectF(half, half, self.width() - BORDER_PX, self.height() - BORDER_PX))

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
        p.drawText(rect, align | Qt.TextFlag.TextWordWrap, text)


@dataclass
class OverlayResult:
    completed: bool
    pauses: list[Interval] = field(default_factory=list)  # real time, the dot waited
    excluded: list[Interval] = field(default_factory=list)  # real time, samples not to use


def run_overlay(
    app: QApplication,
    timeline: list[Step],
    should_stop: Callable[[], bool] = lambda: False,
    face_missing: Callable[[], bool] = lambda: False,
    looking_at: Callable[[], tuple[float, int, float] | None] | None = None,
    pause_on_problems: bool = True,
    wrong_screen_after_s: float = 0.7,
    wrong_screen_conf: float = 0.9,
    max_pause_s: float = 30.0,
) -> OverlayResult:
    """Show the timeline on all screens.

    face_missing() and looking_at() are polled on every frame. looking_at()
    returns (capture time, screen, confidence) from an earlier calibration's
    model, or None; without it, wrong screens are only shown, not detected.
    With pause_on_problems the dot waits while the face is missing or the user
    looks at another screen, and those samples are left out. A pause longer
    than max_pause_s (the user left) aborts the calibration.
    """
    state = {"aborted": False, "stop_requested": False}
    clock = PlaybackClock()
    detector = WrongScreenDetector(wrong_screen_after_s, wrong_screen_conf)
    excluded: list[Interval] = []
    wrong_started: list[float] = []  # capture time where the current wrong-screen spell began

    def abort() -> None:
        state["aborted"] = True
        app.quit()

    screens = ordered_qt_screens()
    rects = [
        (s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height())
        for s in screens
    ]
    windows = []
    for i, screen in enumerate(screens):
        arrows = {j: direction(rects[i], rects[j]) for j in range(len(rects)) if j != i}
        w = ScreenWindow(i, arrows, abort)
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
        real = time.time()
        now = clock.timeline_time(real)
        if now >= end:
            app.quit()
            return
        step = step_at(timeline, now)
        missing = face_missing()
        target = step.screen if step is not None else None
        wrong = detector.update(target, looking_at() if looking_at else None)
        if wrong and not wrong_started:
            wrong_started.append(detector.since or real)
            log.warning("looking at screen %s instead of %s, waiting", detector.looking_at, target)
        elif not wrong and wrong_started:
            excluded.append((wrong_started.pop(), real))
            log.info("back on screen %s, continuing", target)
        if pause_on_problems and step is not None and (missing or wrong):
            clock.pause(real)
            if clock.paused_for(real) > max_pause_s:
                log.error("waited %.0f s for the problem to be fixed, giving up", max_pause_s)
                abort()
                return
        else:
            clock.resume(real)
        for w in windows:
            w.step = step
            w.now = now
            w.face_missing = missing
            w.paused = clock.paused
            w.wrong_here = wrong and detector.looking_at == w.index
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
    real = time.time()
    if wrong_started:
        excluded.append((wrong_started.pop(), real))
    pauses = clock.finish(real)
    if pauses:
        log.info("paused %d time(s), %.1f s in total", len(pauses), sum(b - a for a, b in pauses))
    return OverlayResult(not state["aborted"], pauses, excluded)
