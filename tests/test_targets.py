import pytest

from gaze.config import CalibrationConfig
from gaze.targets import Countdown, Target, build_timeline, grid_points, label_samples, step_at

CFG = CalibrationConfig(
    grid_cols=5,
    grid_rows=3,
    margin=0.1,
    countdown_s=3.0,
    settle_s=0.4,
    record_s=0.6,
    face_warning_s=0.5,
    good_accuracy=0.95,
)


def test_grid_is_snake_ordered_within_margins() -> None:
    pts = grid_points(3, 2, 0.1)
    expected = [(0.1, 0.1), (0.5, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.9), (0.1, 0.9)]
    assert [c for p in pts for c in p] == pytest.approx([c for p in expected for c in p])


def test_single_row_and_column_are_centred() -> None:
    assert grid_points(1, 1, 0.1) == [(0.5, 0.5)]


def test_timeline_layout() -> None:
    tl = build_timeline([0, 1], CFG, start=100.0)
    assert len(tl) == 2 * (1 + 15)
    assert isinstance(tl[0], Countdown) and tl[0].screen == 0 and tl[0].end == pytest.approx(103.0)
    first = tl[1]
    assert isinstance(first, Target)
    assert (first.start, first.record_from, first.end) == pytest.approx((103.0, 103.4, 104.0))
    assert isinstance(tl[16], Countdown) and tl[16].screen == 1
    for a, b in zip(tl, tl[1:], strict=False):
        assert a.end == pytest.approx(b.start)  # no gaps, no overlaps
    assert tl[-1].end == pytest.approx(100 + 2 * (3 + 15 * 1.0))


def test_step_at() -> None:
    tl = build_timeline([0], CFG, start=0.0)
    assert step_at(tl, -0.1) is None
    assert isinstance(step_at(tl, 1.0), Countdown)
    assert step_at(tl, 3.5).number == 1
    assert step_at(tl, tl[-1].end) is None


def test_label_samples_uses_record_window_only() -> None:
    tl = build_timeline([0], CFG, start=0.0)
    samples = [(1.0, "countdown"), (3.2, "settling"), (3.5, "p1"), (4.2, "p2-settle"), (4.7, "p2")]
    labelled = label_samples(tl, samples)
    assert [(t.number, v) for t, v in labelled] == [(1, "p1"), (2, "p2")]
