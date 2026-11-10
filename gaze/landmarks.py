"""MediaPipe Face Landmarker wrapper: frames in, faces out."""

from __future__ import annotations

import logging
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
