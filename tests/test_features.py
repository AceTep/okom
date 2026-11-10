import math

import numpy as np
import pytest

from gaze.features import (
    FEATURE_NAMES,
    LEFT_EYE,
    RIGHT_EYE,
    Face,
    extract,
    head_pose,
    iris_position,
    is_blinking,
    primary_face,
    separation,
)


def rotation(pitch: float, yaw: float, roll: float) -> np.ndarray:
    p, y, r = (math.radians(v) for v in (pitch, yaw, roll))
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = rz @ ry @ rx
    m[:3, 3] = (1.0, -2.0, -50.0)
    return m


@pytest.mark.parametrize("angles", [(0, 0, 0), (15, 0, 0), (-20, 10, 0), (5, -30, 8)])
def test_head_pose_roundtrip(angles) -> None:
    assert head_pose(rotation(*angles)) == pytest.approx(angles, abs=1e-6)


def make_face(iris_offset=(0.0, 0.0), eye_width=40.0, x0=500.0) -> Face:
    """Two horizontal eyes; the irises are shifted by iris_offset * eye_width from centre."""
    pts = np.zeros((478, 2))
    for (left, right, iris), cx in ((RIGHT_EYE, x0), (LEFT_EYE, x0 + 100)):
        pts[left] = (cx - eye_width / 2, 300)
        pts[right] = (cx + eye_width / 2, 300)
        pts[iris] = (cx + iris_offset[0] * eye_width, 300 + iris_offset[1] * eye_width)
    return Face(points=pts, blendshapes={}, matrix=rotation(0, 0, 0))


def test_iris_centred() -> None:
    face = make_face()
    assert iris_position(face.points, RIGHT_EYE) == pytest.approx((0.5, 0.0))
    assert iris_position(face.points, LEFT_EYE) == pytest.approx((0.5, 0.0))


def test_iris_down_and_right_is_positive() -> None:
    face = make_face(iris_offset=(0.1, 0.05))
    h, v = iris_position(face.points, RIGHT_EYE)
    assert h == pytest.approx(0.6) and v == pytest.approx(0.05)


def test_iris_position_independent_of_face_size() -> None:
    small = make_face(iris_offset=(0.1, 0.05), eye_width=20)
    big = make_face(iris_offset=(0.1, 0.05), eye_width=80)
    assert iris_position(small.points, LEFT_EYE) == pytest.approx(
        iris_position(big.points, LEFT_EYE)
    )


def test_iris_position_follows_head_roll() -> None:
    """Rotating the whole eye in the image must not change eye coordinates."""
    face = make_face(iris_offset=(0.1, 0.05))
    a = math.radians(20)
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    rotated = face.points @ rot.T
    assert iris_position(rotated, RIGHT_EYE) == pytest.approx(iris_position(face.points, RIGHT_EYE))


def test_degenerate_eye_does_not_crash() -> None:
    assert iris_position(np.zeros((478, 2)), RIGHT_EYE) == (0.5, 0.0)


def test_extract_vector_matches_names() -> None:
    face = make_face()
    face.blendshapes.update(eyeLookUpLeft=0.2, eyeLookUpRight=0.4, eyeBlinkLeft=0.9)
    f = extract(face)
    assert f.look_up == pytest.approx(0.3)
    assert f.head_z == pytest.approx(-50.0)
    assert f.eye_distance_px == pytest.approx(100.0)
    assert len(f.vector()) == len(FEATURE_NAMES)
    assert is_blinking(f, 0.5) and not is_blinking(f, 0.95)


def test_primary_face_is_largest() -> None:
    near = make_face(x0=100)
    near.points[LEFT_EYE[2]] = near.points[RIGHT_EYE[2]] + (200, 0)
    far = make_face(x0=600)
    assert primary_face([far, near]) is near
    assert primary_face([]) is None


def test_separation() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, (500, 2))
    b = rng.normal(0, 1, (500, 2)) + (5, 0)
    d = separation(a, b)
    assert d[0] == pytest.approx(5, rel=0.15) and d[1] < 0.5
