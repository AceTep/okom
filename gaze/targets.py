"""Where the user should look, and when: the calibration timeline.

Pure logic. The timeline is computed up front from a start time, so the UI
only renders "what is due now" and every camera sample can be labelled
afterwards by its capture timestamp (not by when it was processed).
"""

from __future__ import annotations

from collections.abc import Iterable
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


def label_samples(
    timeline: list[Step], samples: Iterable[tuple[float, T]]
) -> list[tuple[Target, T]]:
    """Pair samples with the target being recorded at their capture time; drop the rest."""
    targets = [s for s in timeline if isinstance(s, Target)]
    out = []
    for t, value in samples:
        for target in targets:
            if target.record_from <= t < target.end:
                out.append((target, value))
                break
    return out
