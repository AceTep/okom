"""One Euro filter, the threshold model's confidence and the outgoing message."""

import numpy as np
import pytest

from gaze.config import load_config
from gaze.features import FEATURE_NAMES
from gaze.main import build_message
from gaze.models import ScreenPredictor, ThresholdClassifier, threshold_proba, train_predictor
from gaze.smoothing import OneEuroFilter
from tests.test_models import fake_session

PITCH = FEATURE_NAMES.index("pitch")


def test_one_euro_removes_jitter_but_follows_steps() -> None:
    f = OneEuroFilter(min_cutoff_hz=1.0, beta=0.05, d_cutoff_hz=1.0)
    rng = np.random.default_rng(0)
    steady = [f(i / 30, np.array([10 + rng.normal(0, 1)]))[0] for i in range(60)]
    assert np.std(steady[30:]) < 0.5  # input std is 1.0
    after = [f(2 + i / 30, np.array([-10.0]))[0] for i in range(15)]  # 20-degree step
    assert after[-1] < -8  # caught up within half a second


def test_one_euro_restarts_after_gap() -> None:
    f = OneEuroFilter(1.0, 0.05, 1.0, reset_after_s=0.5)
    f(0.0, np.array([10.0]))
    assert f(2.0, np.array([-10.0]))[0] == pytest.approx(-10.0)


def test_threshold_confidence() -> None:
    m = ThresholdClassifier().fit(
        np.array([[-20.0], [-18.0], [-6.0], [-4.0]]), np.array([0, 0, 1, 1])
    )
    thr = m.threshold_
    p = threshold_proba(m, np.array([[thr], [thr - 10], [thr + 10]]), softness=2.0)
    assert p[0] == pytest.approx([0.5, 0.5])
    assert p[1][0] > 0.99 and p[2][1] > 0.99  # far below -> screen 0, far above -> screen 1


def vector_with_pitch(pitch: float) -> np.ndarray:
    v = np.zeros(len(FEATURE_NAMES))
    v[PITCH] = pitch
    return v


@pytest.fixture
def predictor(tmp_path) -> ScreenPredictor:
    from gaze.calibration import load, save

    rec = load(save(fake_session(), load_config(), "normal", out_dir=tmp_path))
    pred, _ = train_predictor(rec, "threshold", "head", 0.5, softness=2.0)
    return pred


def test_messages(predictor) -> None:
    up = build_message(1.0, 1, vector_with_pitch(-22.0), False, predictor, 0.55)
    down = build_message(1.0, 1, vector_with_pitch(-3.0), True, predictor, 0.55)
    thr = predictor.model.threshold_
    edge = build_message(1.0, 1, vector_with_pitch(thr), False, predictor, 0.55)
    none = build_message(1.0, 0, None, False, predictor, 0.55)
    assert (up.screen, down.screen) == (0, 1) and up.conf > 0.9
    assert down.blink is True
    assert edge.screen is None and edge.conf == pytest.approx(0.5)  # unsure on the threshold
    assert none.face is False and none.screen is None and none.conf == 0.0


def test_logreg_predictor(tmp_path) -> None:
    from gaze.calibration import load, save

    rec = load(save(fake_session(), load_config(), "normal", out_dir=tmp_path))
    pred, _ = train_predictor(rec, "logreg", "head", 0.5, softness=2.0)
    assert pred.predict(vector_with_pitch(-22.0))[0] == 0
    with pytest.raises(ValueError, match="feature set"):
        train_predictor(rec, "logreg", "nope", 0.5, 2.0)
