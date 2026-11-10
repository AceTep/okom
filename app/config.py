"""Load app/config.yaml into typed dataclasses.

Unknown or missing keys are an error, so a typo in the YAML fails loudly
instead of silently falling back to a default.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

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
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return _build(AppConfig, raw, "config")


def _build(cls: type, raw: Any, where: str) -> Any:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: expected a mapping")
    names = {f.name: f for f in fields(cls)}
    unknown = set(raw) - set(names)
    missing = set(names) - set(raw)
    if unknown or missing:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}")
    values = {}
    for name, f in names.items():
        sub = _SECTIONS.get(f.type)
        values[name] = (
            _build(sub, raw[name], f"{where}.{name}") if sub else _cast(f.type, raw[name])
        )
    return cls(**values)


_SECTIONS: dict[str, type] = {
    "UdpConfig": UdpConfig,
    "DecisionConfig": DecisionConfig,
    "MockGazeConfig": MockGazeConfig,
}


def _cast(type_name: str, value: Any) -> Any:
    caster = {"str": str, "int": int, "float": float}[type_name]
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"expected {type_name}, got {value!r}")
    return caster(value)
