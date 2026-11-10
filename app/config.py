"""Typed view of app/config.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.config import load_dataclass

DEFAULT_PATH = Path(__file__).with_name("config.yaml")


@dataclass(frozen=True, slots=True)
class UdpConfig:
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class DecisionConfig:
    dwell_s: float
    cooldown_s: float
    min_conf: float
    max_gap_s: float


@dataclass(frozen=True, slots=True)
class MockGazeConfig:
    rate_hz: float
    noise_cm: float
    px_per_cm: float
    delay_s: float
    conf: float


@dataclass(frozen=True, slots=True)
class AppConfig:
    udp: UdpConfig
    decision: DecisionConfig
    mock_gaze: MockGazeConfig


def load_config(path: Path | str = DEFAULT_PATH) -> AppConfig:
    return load_dataclass(AppConfig, path)
