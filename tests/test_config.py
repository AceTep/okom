from dataclasses import dataclass

import pytest

from gaze.config import load_config as load_gaze_config
from shared.config import build


@dataclass
class Inner:
    n: int
    ratio: float
    flag: bool


@dataclass
class Outer:
    name: str
    inner: Inner


def test_nested_build() -> None:
    cfg = build(Outer, {"name": "a", "inner": {"n": 1, "ratio": 2, "flag": True}}, "t")
    assert cfg.inner.ratio == 2.0 and isinstance(cfg.inner.ratio, float)


@pytest.mark.parametrize(
    "inner",
    [
        {"n": True, "ratio": 1.0, "flag": True},  # bool is not an int
        {"n": 1.5, "ratio": 1.0, "flag": True},  # float is not an int
        {"n": 1, "ratio": "x", "flag": True},
        {"n": 1, "ratio": 1.0, "flag": 1},  # int is not a bool
        {"n": 1, "ratio": 1.0},  # missing key
        {"n": 1, "ratio": 1.0, "flag": True, "extra": 0},  # unknown key
    ],
)
def test_build_rejects(inner: dict) -> None:
    with pytest.raises(ValueError):
        build(Outer, {"name": "a", "inner": inner}, "t")


def test_gaze_config_loads() -> None:
    cfg = load_gaze_config()
    assert cfg.camera.device == 0 and cfg.camera.fourcc == "MJPG"
