"""Typed view of gaze/config.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.config import load_dataclass

DEFAULT_PATH = Path(__file__).with_name("config.yaml")


@dataclass(frozen=True, slots=True)
class CameraConfig:
    device: int
    width: int
    height: int
    fps: int
    fourcc: str
    fixed_framerate: bool


@dataclass(frozen=True, slots=True)
class LandmarksConfig:
    model_path: str
    num_faces: int
    min_detection_confidence: float
    min_presence_confidence: float
    min_tracking_confidence: float


@dataclass(frozen=True, slots=True)
class FeaturesConfig:
    blink_threshold: float


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    grid_cols: int
    grid_rows: int
    margin: float
    countdown_s: float
    settle_s: float
    record_s: float


@dataclass(frozen=True, slots=True)
class GazeConfig:
    camera: CameraConfig
    landmarks: LandmarksConfig
    features: FeaturesConfig
    calibration: CalibrationConfig


def load_config(path: Path | str = DEFAULT_PATH) -> GazeConfig:
    return load_dataclass(GazeConfig, path)
