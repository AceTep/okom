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
class GazeConfig:
    camera: CameraConfig


def load_config(path: Path | str = DEFAULT_PATH) -> GazeConfig:
    return load_dataclass(GazeConfig, path)
