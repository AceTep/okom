import json

import pytest

from shared.protocol import GazeMessage, ProtocolError
from shared.screens import order_screens

EXAMPLE = (
    '{"t": 1730543000.123, "face": true, "users": 1, "screen": 1,'
    ' "x": 0.42, "y": 0.71, "conf": 0.86, "blink": false}'
)


def make(**overrides) -> dict:
    base = json.loads(EXAMPLE)
    base.update(overrides)
    return base


def test_parse_example() -> None:
    msg = GazeMessage.from_json(EXAMPLE)
    assert msg.screen == 1
    assert msg.x == pytest.approx(0.42)
    assert msg.face is True


def test_roundtrip() -> None:
    msg = GazeMessage.from_json(EXAMPLE)
    assert GazeMessage.from_json(msg.to_json()) == msg


def test_screen_null() -> None:
    assert GazeMessage.from_json(json.dumps(make(screen=None))).screen is None


def test_unknown_fields_ignored() -> None:
    msg = GazeMessage.from_json(json.dumps(make(extra=123)))
    assert msg.users == 1


def test_integral_floats_accepted() -> None:
    msg = GazeMessage.from_json(json.dumps(make(t=1730543000, x=0, conf=1)))
    assert isinstance(msg.t, float) and isinstance(msg.x, float)


def test_bytes_accepted() -> None:
    assert GazeMessage.from_json(EXAMPLE.encode()).users == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"x": 1.5},
        {"y": -0.1},
        {"conf": 2},
        {"screen": -1},
        {"screen": 0.5},
        {"users": -1},
        {"users": True},
        {"face": 1},
        {"blink": "no"},
        {"t": "now"},
    ],
)
def test_invalid_values(overrides: dict) -> None:
    with pytest.raises(ProtocolError):
        GazeMessage.from_json(json.dumps(make(**overrides)))


def test_missing_field() -> None:
    data = make()
    del data["conf"]
    with pytest.raises(ProtocolError, match="conf"):
        GazeMessage.from_json(json.dumps(data))


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", b"\xff\xfe"])
def test_garbage(raw) -> None:
    with pytest.raises(ProtocolError):
        GazeMessage.from_json(raw)


def test_nan_rejected() -> None:
    with pytest.raises(ProtocolError):
        GazeMessage.from_json(EXAMPLE.replace("0.42", "NaN"))


def test_screen_order_monitor_above_laptop() -> None:
    screens = [("eDP-1", 0, 1440), ("DP-1", -320, 0)]
    assert [s[0] for s in order_screens(screens, key=lambda s: s)] == ["DP-1", "eDP-1"]


def test_screen_order_side_by_side() -> None:
    screens = [("B", 1920, 0), ("A", 0, 0)]
    assert [s[0] for s in order_screens(screens, key=lambda s: s)] == ["A", "B"]
