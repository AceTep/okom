"""Calibration save/load and the screen models, on synthetic faces."""

import numpy as np
import pytest

from gaze.calibration import load, save
from gaze.config import load_config
from gaze.features import FEATURE_NAMES, RIGHT_EYE, Face
from gaze.models import (
    ThresholdClassifier,
    build_dataset,
    leave_one_point_out,
    make_logreg,
)
from gaze.session import Sample, SessionResult
from gaze.targets import Target, build_timeline
from tests.test_features import make_face, rotation


def fake_session(pitch_by_screen=(-20.0, -5.0), noise=1.0, seed=0) -> SessionResult:
    """Two screens, 5x3 points, 30 Hz; pitch depends on screen and point row."""
    cfg = load_config()
    timeline = build_timeline([0, 1], cfg.calibration, start=1000.0)
    rng = np.random.default_rng(seed)
    samples = []
    t = 1000.0
    while t < timeline[-1].end:
        target = next((s for s in timeline if s.start <= t < s.end), None)
        face = make_face()
        if isinstance(target, Target):
            pitch = pitch_by_screen[target.screen] + 6 * (target.y - 0.5) + rng.normal(0, noise)
            face = Face(face.points, {"eyeBlinkLeft": 0.0}, rotation(pitch, 0, 0))
        samples.append(Sample(t, face, 1))
        t += 1 / 30
    screens = [("HDMI-A-1", 0, 0, 1920, 1080), ("eDP-1", 0, 1080, 1920, 1080)]
    return SessionResult(timeline, samples, True, screens)


def test_save_load_roundtrip(tmp_path) -> None:
    cfg = load_config()
    path = save(fake_session(), cfg, "normal", out_dir=tmp_path)
    rec = load(path)
    assert rec.condition == "normal"
    n = 2 * 15 * round(cfg.calibration.record_s * 30)
    assert abs(len(rec.t) - n) <= 30  # frame boundaries may add or drop one per point
    assert set(rec.screen) == {0, 1} and set(rec.point) == set(range(1, 16))
    face = rec.face(0)
    assert face is not None and face.points[RIGHT_EYE[2]] == pytest.approx((500.0, 300.0))
    assert rec.meta["screens"][1]["name"] == "eDP-1"


def test_save_refuses_to_overwrite(tmp_path) -> None:
    cfg = load_config()
    session = fake_session()
    save(session, cfg, "normal", out_dir=tmp_path)
    with pytest.raises(FileExistsError):
        save(session, cfg, "normal", out_dir=tmp_path)


def test_dataset_groups_and_rows(tmp_path) -> None:
    rec = load(save(fake_session(), load_config(), "normal", out_dir=tmp_path))
    data = build_dataset([rec], ("pitch",), blink_threshold=0.5)
    assert len(np.unique(data.group)) == 30  # 2 screens x 15 points
    assert set(data.row) == {0, 1, 2}
    assert data.x.shape == (len(data.screen), 1)


def test_threshold_classifier() -> None:
    x = np.array([[-20.0], [-18.0], [-6.0], [-4.0]])
    y = np.array([0, 0, 1, 1])
    m = ThresholdClassifier().fit(x, y)
    assert list(m.predict(np.array([[-25.0], [-12.5 - 0.1], [0.0]]))) == [0, 0, 1]
    assert -18 < m.threshold_ < -6


def test_lopo_separable_and_not(tmp_path) -> None:
    good = load(save(fake_session(noise=1.0), load_config(), "a", out_dir=tmp_path))
    data = build_dataset([good], ("pitch",), 0.5)
    assert np.mean(leave_one_point_out(data, make_logreg) == data.screen) > 0.99

    same = load(save(fake_session((-10.0, -10.0)), load_config(), "b", out_dir=tmp_path))
    data = build_dataset([same], ("pitch",), 0.5)
    assert np.mean(leave_one_point_out(data, ThresholdClassifier) == data.screen) < 0.75


def test_feature_names_cover_sets() -> None:
    from gaze.models import FEATURE_SETS

    for names in FEATURE_SETS.values():
        assert all(n in FEATURE_NAMES for n in names)


def test_lopo_refuses_one_sided_data(tmp_path) -> None:
    session = fake_session()
    session.samples[:] = [
        s
        for s in session.samples
        if not any(
            isinstance(st, Target) and st.screen == 1 and st.start <= s.t < st.end
            for st in session.timeline
        )
    ]
    rec = load(save(session, load_config(), "one", out_dir=tmp_path))
    data = build_dataset([rec], ("pitch",), 0.5)
    with pytest.raises(ValueError, match="screen"):
        leave_one_point_out(data, make_logreg)


def drop_faces(session, screen=None, points=None):
    """Remove the face from samples recorded on a screen (optionally only some points)."""
    for i, sample in enumerate(session.samples):
        target = next(
            (
                st
                for st in session.timeline
                if isinstance(st, Target) and st.start <= sample.t < st.end
            ),
            None,
        )
        if target and target.screen == screen and (points is None or target.number in points):
            session.samples[i] = Sample(sample.t, None, 0)
    return session


def quality_of(session, tmp_path, name):
    from gaze.calibration import record_quality

    cfg = load_config()
    return record_quality(save(session, cfg, name, out_dir=tmp_path), cfg)


def test_quality_good(tmp_path) -> None:
    q = quality_of(fake_session(), tmp_path, "good")
    assert q.verdict == "good" and q.accuracy > 0.95
    assert load(next(tmp_path.iterdir())).meta["quality"]["verdict"] == "good"  # stored


def test_quality_weak_when_screens_look_alike(tmp_path) -> None:
    q = quality_of(fake_session((-10.0, -9.0), noise=3.0), tmp_path, "weak")
    assert q.verdict == "weak" and "too alike" in q.message


def test_quality_unusable_without_face_on_a_screen(tmp_path) -> None:
    q = quality_of(drop_faces(fake_session(), screen=1), tmp_path, "noface")
    assert q.verdict == "unusable" and q.accuracy is None
    assert "0 of 15 points on screen 1 (eDP-1)" in q.message


def test_quality_hint_when_face_often_missing(tmp_path) -> None:
    session = drop_faces(fake_session(), screen=0, points=set(range(1, 10)))
    q = quality_of(session, tmp_path, "dim")
    assert "check the light" in q.message
