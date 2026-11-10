import dataclasses

import pytest

from gaze.config import load_config
from gaze.targets import Countdown, Target, build_timeline, grid_points, label_samples, step_at

CFG = dataclasses.replace(
    load_config().calibration,
    grid_cols=5,
    grid_rows=3,
    margin=0.1,
    countdown_s=3.0,
    settle_s=0.4,
    record_s=0.6,
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


def test_timeline_time_stands_still_during_pauses() -> None:
    from gaze.targets import to_timeline_time

    pauses = [(10.0, 12.0), (20.0, 21.0)]
    assert to_timeline_time(5.0, pauses) == 5.0
    assert to_timeline_time(11.0, pauses) == 10.0  # inside a pause
    assert to_timeline_time(15.0, pauses) == 13.0
    assert to_timeline_time(30.0, pauses) == 27.0


def test_playback_clock() -> None:
    from gaze.targets import PlaybackClock

    c = PlaybackClock()
    assert c.timeline_time(5.0) == 5.0
    c.pause(5.0)
    assert c.paused and c.timeline_time(7.0) == 5.0
    c.resume(7.0)
    assert c.timeline_time(8.0) == 6.0
    assert c.finish(9.0) == [(5.0, 7.0)]


def test_labels_follow_pauses_and_drop_excluded() -> None:
    tl = build_timeline([0], CFG, start=0.0)  # point 1 records 3.4-4.0, point 2 records 4.4-5.0
    pauses = [(3.5, 5.5)]  # paused 2 s during point 1
    samples = [(3.45, "p1"), (4.0, "paused"), (5.6, "p1-late"), (6.0, "p1-excl"), (6.5, "p2")]
    labelled = label_samples(tl, samples, pauses=pauses, excluded=[(5.9, 6.1)])
    assert [(t.number, v) for t, v in labelled] == [(1, "p1"), (1, "p1-late"), (2, "p2")]


def test_wrong_screen_detector() -> None:
    from gaze.targets import WrongScreenDetector

    d = WrongScreenDetector(after_s=0.5, min_conf=0.9)
    assert d.update(0, (0.0, 1, 0.99)) is False  # just started looking away
    assert d.update(0, (0.3, 1, 0.99)) is False  # short glance is fine
    assert d.update(0, (0.6, 1, 0.99)) is True and d.since == 0.0 and d.looking_at == 1
    assert d.update(0, (0.7, 0, 0.6)) is True  # unsure prediction: no change
    assert d.update(0, None) is True  # no face: no change
    assert d.update(0, (0.8, 0, 0.95)) is False  # back on the right screen
    assert d.update(0, (0.9, 1, 0.7)) is False  # near the border, unsure: no alarm


def test_direction() -> None:
    from gaze.targets import direction

    monitor, laptop = (0, 0, 1920, 1080), (0, 1080, 1920, 1080)
    assert direction(laptop, monitor) == ("↑", "ABOVE")
    assert direction(monitor, laptop) == ("↓", "BELOW")
    assert direction((0, 0, 1920, 1080), (1920, 0, 1920, 1080))[0] == "→"


def test_paused_for() -> None:
    from gaze.targets import PlaybackClock

    c = PlaybackClock()
    assert c.paused_for(5.0) == 0.0
    c.pause(5.0)
    assert c.paused_for(8.0) == 3.0
