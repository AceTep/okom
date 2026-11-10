"""Where the user should look, and when: the calibration timeline.

Pure logic. The timeline is computed up front from a start time, so the UI
only renders "what is due now" and every camera sample can be labelled
afterwards by its capture timestamp (not by when it was processed).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from gaze.config import CalibrationConfig

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Countdown:
    screen: int
    start: float
    end: float
    first_x: float  # first point of the screen, shown during the countdown
    first_y: float


@dataclass(frozen=True, slots=True)
class Target:
    screen: int
    x: float  # normalized 0..1 within the screen
    y: float
    start: float  # dot appears
    record_from: float  # eyes have settled, samples from here count
    end: float
    number: int  # 1-based position within this screen's points
    total: int


Step = Countdown | Target


def grid_points(cols: int, rows: int, margin: float) -> list[tuple[float, float]]:
    """Grid in snake order (row by row, alternating direction) to keep jumps short."""

    def axis(n: int) -> list[float]:
        if n == 1:
            return [0.5]
        return [margin + i * (1 - 2 * margin) / (n - 1) for i in range(n)]

    xs, ys = axis(cols), axis(rows)
    points = []
    for r, y in enumerate(ys):
        row = xs if r % 2 == 0 else list(reversed(xs))
        points.extend((x, y) for x in row)
    return points


def build_timeline(screens: Iterable[int], cfg: CalibrationConfig, start: float) -> list[Step]:
    points = grid_points(cfg.grid_cols, cfg.grid_rows, cfg.margin)
    steps: list[Step] = []
    t = start
    for screen in screens:
        steps.append(Countdown(screen, t, t + cfg.countdown_s, *points[0]))
        t += cfg.countdown_s
        for i, (x, y) in enumerate(points, start=1):
            end = t + cfg.settle_s + cfg.record_s
            steps.append(Target(screen, x, y, t, t + cfg.settle_s, end, i, len(points)))
            t = end
    return steps


def step_at(timeline: list[Step], t: float) -> Step | None:
    """The step due at time t, None before the start and after the end."""
    for step in timeline:
        if step.start <= t < step.end:
            return step
    return None


Interval = tuple[float, float]  # (start, end) in real (wall-clock) time


def to_timeline_time(t: float, pauses: Sequence[Interval]) -> float:
    """Real time -> timeline time: the timeline stands still during pauses."""
    shift = 0.0
    for start, end in pauses:
        if t >= end:
            shift += end - start
        elif t > start:
            shift += t - start
    return t - shift


def label_samples(
    timeline: list[Step],
    samples: Iterable[tuple[float, T]],
    pauses: Sequence[Interval] = (),
    excluded: Sequence[Interval] = (),
) -> list[tuple[Target, T]]:
    """Pair samples with the target being recorded at their capture time; drop the rest.

    Capture times are real times; `pauses` map them onto the timeline. Samples
    taken during a pause or inside an `excluded` interval (e.g. the moments
    before a wrong-screen pause kicked in) are dropped.
    """
    targets = [s for s in timeline if isinstance(s, Target)]
    out = []
    for t, value in samples:
        if any(a <= t < b for a, b in (*pauses, *excluded)):
            continue  # paused or excluded: the user was not looking where they should
        tt = to_timeline_time(t, pauses)
        for target in targets:
            if target.record_from <= tt < target.end:
                out.append((target, value))
                break
    return out


class PlaybackClock:
    """Timeline time that can be paused, and the record of every pause."""

    def __init__(self) -> None:
        self.pauses: list[Interval] = []
        self._paused_at: float | None = None

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def paused_for(self, now: float) -> float:
        """Length of the current pause, 0 when running."""
        return 0.0 if self._paused_at is None else now - self._paused_at

    def pause(self, now: float) -> None:
        if self._paused_at is None:
            self._paused_at = now

    def resume(self, now: float) -> None:
        if self._paused_at is not None:
            self.pauses.append((self._paused_at, now))
            self._paused_at = None

    def timeline_time(self, now: float) -> float:
        pauses = self.pauses + ([(self._paused_at, now)] if self._paused_at is not None else [])
        return to_timeline_time(now, pauses)

    def finish(self, now: float) -> list[Interval]:
        self.resume(now)
        return list(self.pauses)


class WrongScreenDetector:
    """Is the user looking at another screen than the one being calibrated?

    Uses a model from an earlier calibration. Only confident predictions count,
    so points near the border between screens (where any model is unsure) do
    not raise false alarms. A short glance is tolerated (`after_s`).
    """

    def __init__(self, after_s: float, min_conf: float) -> None:
        self.after_s = after_s
        self.min_conf = min_conf
        self.wrong = False
        self.since: float | None = None  # capture time when the mismatch began
        self.looking_at: int | None = None

    def update(
        self, target_screen: int | None, prediction: tuple[float, int, float] | None
    ) -> bool:
        """prediction: (capture time, screen, confidence) or None when there is no face."""
        if target_screen is None or prediction is None:
            return self.wrong
        t, screen, conf = prediction
        if conf < self.min_conf:
            return self.wrong  # unsure: keep the current state
        if screen == target_screen:
            self.wrong, self.since, self.looking_at = False, None, None
            return False
        if self.since is None:
            self.since = t
        self.looking_at = screen
        if t - self.since >= self.after_s:
            self.wrong = True
        return self.wrong


Rect = tuple[int, int, int, int]  # x, y, w, h


def direction(from_rect: Rect, to_rect: Rect) -> tuple[str, str]:
    """(arrow, word) pointing from one screen to another, e.g. ("↑", "ABOVE")."""
    fx, fy = from_rect[0] + from_rect[2] / 2, from_rect[1] + from_rect[3] / 2
    tx, ty = to_rect[0] + to_rect[2] / 2, to_rect[1] + to_rect[3] / 2
    dx, dy = tx - fx, ty - fy
    if abs(dy) >= abs(dx):
        return ("↑", "ABOVE") if dy < 0 else ("↓", "BELOW")
    return ("←", "on the LEFT") if dx < 0 else ("→", "on the RIGHT")
