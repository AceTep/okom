"""Gaze features from one face: head pose, iris position in the eye, blendshapes.

Pure functions on numpy arrays, no camera and no MediaPipe needed, so all of
it is unit-tested with synthetic faces.

Eye landmarks (MediaPipe face mesh, image not mirrored):
- the subject's right eye appears on the image left: corners 33 (outer) and
  133 (inner), iris centre 468;
- the subject's left eye appears on the image right: corners 362 (inner) and
  263 (outer), iris centre 473.
"""

from __future__ import annotations

import math
from dataclasses import astuple, dataclass, fields

import numpy as np


@dataclass(frozen=True, slots=True)
class Face:
    """One detected face (filled by gaze.landmarks)."""

    points: np.ndarray  # (478, 2) landmark positions in image pixels (x right, y down)
    blendshapes: dict[str, float]  # 52 ARKit-style scores 0..1, e.g. "eyeLookUpLeft"
    matrix: np.ndarray  # (4, 4) facial transformation: head rotation + translation (cm)


# (image-left corner, image-right corner, iris centre) per eye
RIGHT_EYE = (33, 133, 468)
LEFT_EYE = (362, 263, 473)


@dataclass(frozen=True, slots=True)
class Features:
    pitch: float  # head rotation about the horizontal axis, degrees
    yaw: float  # head rotation about the vertical axis, degrees
    roll: float  # head tilt in the image plane, degrees
    head_x: float  # head position relative to the camera, cm
    head_y: float
    head_z: float
    iris_h_right: float  # iris along the corner-to-corner line: 0 image-left .. 1 image-right
    iris_v_right: float  # iris offset from that line / eye width, positive = image-down
    iris_h_left: float
    iris_v_left: float
    look_up: float  # blendshape eyeLookUp, mean of both eyes, 0..1
    look_down: float  # blendshape eyeLookDown, mean of both eyes, 0..1
    blink_right: float  # blendshape eyeBlink, 0..1
    blink_left: float
    eye_distance_px: float  # distance between iris centres; face size in the image

    def vector(self) -> np.ndarray:
        return np.array(astuple(self), dtype=np.float64)


FEATURE_NAMES: tuple[str, ...] = tuple(f.name for f in fields(Features))


def head_pose(matrix: np.ndarray) -> tuple[float, float, float]:
    """(pitch, yaw, roll) in degrees from a 4x4 transform, R = Rz(roll) Ry(yaw) Rx(pitch)."""
    r = matrix[:3, :3]
    yaw = math.asin(max(-1.0, min(1.0, -r[2, 0])))
    pitch = math.atan2(r[2, 1], r[2, 2])
    roll = math.atan2(r[1, 0], r[0, 0])
    return math.degrees(pitch), math.degrees(yaw), math.degrees(roll)


def iris_position(points: np.ndarray, eye: tuple[int, int, int]) -> tuple[float, float]:
    """Iris centre in eye coordinates, scaled by eye width.

    h: 0 at the image-left corner, 1 at the image-right corner.
    v: distance from the corner-to-corner line, positive towards image-down.
    """
    a, b, c = points[eye[0]], points[eye[1]], points[eye[2]]
    axis = b - a
    width = float(np.linalg.norm(axis))
    if width < 1e-6:
        return 0.5, 0.0
    u = axis / width
    n = np.array([-u[1], u[0]])  # u rotated by +90 deg: image-down when u points right
    rel = c - a
    return float(rel @ u) / width, float(rel @ n) / width


def extract(face: Face) -> Features:
    pitch, yaw, roll = head_pose(face.matrix)
    hx, hy, hz = (float(v) for v in face.matrix[:3, 3])
    rh, rv = iris_position(face.points, RIGHT_EYE)
    lh, lv = iris_position(face.points, LEFT_EYE)
    bs = face.blendshapes
    return Features(
        pitch=pitch,
        yaw=yaw,
        roll=roll,
        head_x=hx,
        head_y=hy,
        head_z=hz,
        iris_h_right=rh,
        iris_v_right=rv,
        iris_h_left=lh,
        iris_v_left=lv,
        look_up=(bs.get("eyeLookUpLeft", 0.0) + bs.get("eyeLookUpRight", 0.0)) / 2,
        look_down=(bs.get("eyeLookDownLeft", 0.0) + bs.get("eyeLookDownRight", 0.0)) / 2,
        blink_right=bs.get("eyeBlinkRight", 0.0),
        blink_left=bs.get("eyeBlinkLeft", 0.0),
        eye_distance_px=float(np.linalg.norm(face.points[RIGHT_EYE[2]] - face.points[LEFT_EYE[2]])),
    )


def primary_face(faces: list[Face]) -> Face | None:
    """The face closest to the camera (largest in the image)."""
    if not faces:
        return None
    return max(faces, key=lambda f: np.linalg.norm(f.points[RIGHT_EYE[2]] - f.points[LEFT_EYE[2]]))


def is_blinking(f: Features, threshold: float) -> bool:
    return max(f.blink_left, f.blink_right) >= threshold


def separation(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Per-column d' = |mean_a - mean_b| / pooled std; > 2 separates well, > 4 very well."""
    pooled = np.sqrt((a.var(axis=0, ddof=1) + b.var(axis=0, ddof=1)) / 2)
    return np.abs(a.mean(axis=0) - b.mean(axis=0)) / np.maximum(pooled, 1e-9)
