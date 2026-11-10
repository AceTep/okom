"""Screen classifiers and an honest way to measure them.

Consecutive frames looking at the same point are nearly identical, so a
random train/test split would leak and inflate accuracy. Evaluation therefore
holds out whole calibration points: train on all other points, test on the
held-out one (leave-one-point-out), or train on one recording and test on
another.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from gaze.calibration import Recording
from gaze.features import FEATURE_NAMES, is_blinking

HEAD = ("pitch", "yaw", "roll")
EYES = ("iris_h_right", "iris_v_right", "iris_h_left", "iris_v_left")
# Where the head is, not where it points: depends on how the user sits.
POSTURE = ("head_x", "head_y", "head_z", "eye_distance_px")

FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "head": HEAD,
    "eyes": EYES,
    "head+eyes": HEAD + EYES,
    "head+eyes+posture": HEAD + EYES + POSTURE,
}


class ThresholdClassifier:
    """Two screens split by one threshold on one feature. The simplest baseline."""

    def fit(self, x: np.ndarray, y: np.ndarray) -> ThresholdClassifier:
        v = x[:, 0]
        self.classes_ = np.unique(y)
        if len(self.classes_) != 2:
            raise ValueError("threshold classifier needs exactly two classes")
        lo, hi = self.classes_
        best = (-1.0, 0.0, True)
        candidates = np.unique(v)
        mids = (candidates[:-1] + candidates[1:]) / 2 if len(candidates) > 1 else candidates
        for thr in mids:
            for below_is_lo in (True, False):
                pred = np.where((v < thr) == below_is_lo, lo, hi)
                acc = float(np.mean(pred == y))
                if acc > best[0]:
                    best = (acc, float(thr), below_is_lo)
        _, self.threshold_, self.below_is_lo_ = best
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        lo, hi = self.classes_
        return np.where((x[:, 0] < self.threshold_) == self.below_is_lo_, lo, hi)


def make_logreg():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))


MODELS: dict[str, tuple[Callable[[], object], tuple[str, ...] | None]] = {
    # name: (factory, fixed feature set or None = try every FEATURE_SETS entry)
    "threshold(pitch)": (ThresholdClassifier, ("pitch",)),
    "logreg": (make_logreg, None),
}


@dataclass
class Dataset:
    x: np.ndarray  # (N, F) selected features
    screen: np.ndarray  # (N,) label
    group: np.ndarray  # (N,) one id per (recording, screen, point): the unit held out
    row: np.ndarray  # (N,) row of the point within its screen, 0 = top
    names: tuple[str, ...]
    skipped_no_face: int
    skipped_blink: int


def build_dataset(
    recordings: Sequence[Recording], names: Sequence[str], blink_threshold: float
) -> Dataset:
    cols = [FEATURE_NAMES.index(n) for n in names]
    xs, screens, groups, rows = [], [], [], []
    no_face = blink = 0
    for r_i, rec in enumerate(recordings):
        y_rounded = np.round(rec.y.astype(np.float64), 4)
        row_of_sample = np.searchsorted(np.unique(y_rounded), y_rounded)
        for i, f in enumerate(rec.features()):
            if f is None:
                no_face += 1
                continue
            if is_blinking(f, blink_threshold):
                blink += 1
                continue
            xs.append(f.vector()[cols])
            screens.append(int(rec.screen[i]))
            groups.append(r_i * 10_000 + int(rec.screen[i]) * 100 + int(rec.point[i]))
            rows.append(int(row_of_sample[i]))
    return Dataset(
        x=np.array(xs).reshape(-1, len(cols)),
        screen=np.array(screens),
        group=np.array(groups),
        row=np.array(rows),
        names=tuple(names),
        skipped_no_face=no_face,
        skipped_blink=blink,
    )


def coverage_problem(data: Dataset, min_points: int = 2) -> str | None:
    """Why the data cannot be evaluated, or None if it can."""
    screens = np.unique(data.screen)
    if len(screens) < 2:
        return f"samples with a face on {len(screens)} screen(s), need at least 2"
    for s in screens:
        points = len(np.unique(data.group[data.screen == s]))
        if points < min_points:
            return f"screen {s} has a face on only {points} point(s), need at least {min_points}"
    return None


def leave_one_point_out(data: Dataset, factory: Callable[[], object]) -> np.ndarray:
    """Prediction for every sample from a model that never saw that sample's point."""
    problem = coverage_problem(data)
    if problem:
        raise ValueError(problem)
    pred = np.empty_like(data.screen)
    for g in np.unique(data.group):
        test = data.group == g
        model = factory().fit(data.x[~test], data.screen[~test])
        pred[test] = model.predict(data.x[test])
    return pred


def train_test(train: Dataset, test: Dataset, factory: Callable[[], object]) -> np.ndarray:
    return factory().fit(train.x, train.screen).predict(test.x)


def threshold_proba(model: ThresholdClassifier, x: np.ndarray, softness: float) -> np.ndarray:
    """Class probabilities for the threshold model: 0.5 on the threshold, -> 1 away from it.

    p(lo) = sigmoid(signed distance / softness), where the sign points to lo's side.
    """
    distance = (model.threshold_ - x[:, 0]) if model.below_is_lo_ else (x[:, 0] - model.threshold_)
    p_lo = 1.0 / (1.0 + np.exp(-distance / softness))
    return np.column_stack([p_lo, 1.0 - p_lo])


class ScreenPredictor:
    """A trained screen model applied to one Features vector at a time."""

    def __init__(self, kind: str, names: tuple[str, ...], model, softness: float) -> None:
        self.kind = kind
        self.names = names
        self.model = model
        self.softness = softness
        self._cols = [FEATURE_NAMES.index(n) for n in names]

    @property
    def classes(self) -> np.ndarray:
        return self.model.classes_

    def predict(self, vector: np.ndarray) -> tuple[int, float]:
        """(screen, confidence) for a full feature vector (FEATURE_NAMES order)."""
        x = np.asarray(vector, dtype=np.float64)[self._cols].reshape(1, -1)
        if isinstance(self.model, ThresholdClassifier):
            proba = threshold_proba(self.model, x, self.softness)[0]
        else:
            proba = self.model.predict_proba(x)[0]
        best = int(np.argmax(proba))
        return int(self.classes[best]), float(proba[best])


def train_predictor(
    recording: Recording, kind: str, feature_set: str, blink_threshold: float, softness: float
) -> tuple[ScreenPredictor, Dataset]:
    if kind == "threshold":
        names: tuple[str, ...] = ("pitch",)
        model = ThresholdClassifier()
    elif kind == "logreg":
        if feature_set not in FEATURE_SETS:
            raise ValueError(
                f"unknown feature set {feature_set!r}, choose from {list(FEATURE_SETS)}"
            )
        names = FEATURE_SETS[feature_set]
        model = make_logreg()
    else:
        raise ValueError(f"unknown model kind {kind!r}, choose threshold or logreg")
    data = build_dataset([recording], names, blink_threshold)
    problem = coverage_problem(data)
    if problem:
        raise ValueError(f"{recording.path.name}: {problem}")
    model.fit(data.x, data.screen)
    return ScreenPredictor(kind, names, model, softness), data
