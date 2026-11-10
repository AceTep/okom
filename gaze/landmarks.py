"""MediaPipe Face Landmarker wrapper: frames in, faces out."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from gaze.camera import Frame
from gaze.config import LandmarksConfig
from gaze.features import Face

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent


class LandmarkDetector:
    def __init__(self, cfg: LandmarksConfig) -> None:
        model = Path(cfg.model_path)
        if not model.is_absolute():
            model = REPO_ROOT / model
        if not model.exists():
            raise FileNotFoundError(f"{model} missing, run: python scripts/download_models.py")
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=cfg.num_faces,
            min_face_detection_confidence=cfg.min_detection_confidence,
            min_face_presence_confidence=cfg.min_presence_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        if cfg.quiet_native_logs:
            with _captured_native_stderr() as output:
                try:
                    self._landmarker = vision.FaceLandmarker.create_from_options(options)
                except Exception:
                    output.failed = True
                    raise
            # fd 2 is restored here, so these messages reach the terminal
            if output.failed:
                log.error("MediaPipe output while loading:\n%s", output.text)
            else:
                log.debug("MediaPipe output while loading (hidden):\n%s", output.text)
        else:
            self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_ms = -1

    def detect(self, frame: Frame) -> list[Face]:
        h, w = frame.image.shape[:2]
        rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
        # VIDEO mode needs strictly increasing timestamps.
        ms = max(int(frame.t * 1000), self._last_ms + 1)
        self._last_ms = ms
        result = self._landmarker.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms
        )
        faces = []
        for lms, shapes, matrix in zip(
            result.face_landmarks,
            result.face_blendshapes,
            result.facial_transformation_matrixes,
            strict=True,
        ):
            points = np.array([(p.x * w, p.y * h) for p in lms], dtype=np.float64)
            faces.append(
                Face(
                    points=points,
                    blendshapes={c.category_name: float(c.score) for c in shapes},
                    matrix=np.asarray(matrix, dtype=np.float64),
                )
            )
        return faces

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> LandmarkDetector:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _Captured:
    text = ""
    failed = False


@contextmanager
def _captured_native_stderr() -> Iterator[_Captured]:
    """Send C-level stderr (fd 2) to a temporary file while the block runs.

    MediaPipe's C++ code prints a handful of harmless warnings while the model
    loads. Python's sys.stderr is not involved, so the file descriptor itself
    is redirected. The captured text is available after the block, when fd 2
    is back to normal, so nothing logged afterwards is lost.
    """
    result = _Captured()
    sys.stderr.flush()
    saved = os.dup(2)
    with tempfile.TemporaryFile() as tmp:
        os.dup2(tmp.fileno(), 2)
        try:
            yield result
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            tmp.seek(0)
            result.text = tmp.read().decode(errors="replace").strip()
