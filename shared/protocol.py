"""Gaze message exchanged between gaze/ and app/ over UDP.

One JSON object per UDP datagram, about 30 Hz. This module is the single
source of truth for the format: both sides use GazeMessage.to_json() and
GazeMessage.from_json(), nobody parses the JSON by hand.

Fields may be added; existing fields must not be renamed, retyped or removed.
Unknown fields in incoming messages are ignored so that a newer sender keeps
working with an older receiver.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555


class ProtocolError(ValueError):
    """Raised when a message does not match the protocol."""


@dataclass(frozen=True, slots=True)
class GazeMessage:
    t: float  # Unix time in seconds
    face: bool  # calibrated user is in frame
    users: int  # number of faces in frame
    screen: int | None  # screen index 0..N-1, None when unsure
    x: float  # gaze point within the screen, normalized 0..1
    y: float
    conf: float  # confidence 0..1
    blink: bool  # a blink is in progress

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        _check_number("t", self.t)
        _check_bool("face", self.face)
        _check_int("users", self.users)
        if self.users < 0:
            raise ProtocolError(f"users must be >= 0, got {self.users}")
        if self.screen is not None:
            _check_int("screen", self.screen)
            if self.screen < 0:
                raise ProtocolError(f"screen must be >= 0 or null, got {self.screen}")
        for name in ("x", "y", "conf"):
            value = getattr(self, name)
            _check_number(name, value)
            if not 0.0 <= value <= 1.0:
                raise ProtocolError(f"{name} must be in [0, 1], got {value}")
        _check_bool("blink", self.blink)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, data: str | bytes) -> GazeMessage:
        try:
            obj = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProtocolError(f"not valid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise ProtocolError(f"expected a JSON object, got {type(obj).__name__}")
        names = [f.name for f in fields(cls)]
        missing = [n for n in names if n not in obj]
        if missing:
            raise ProtocolError(f"missing fields: {', '.join(missing)}")
        values = {n: obj[n] for n in names}
        # JSON has one number type; accept integral values for float fields.
        for n in ("t", "x", "y", "conf"):
            if isinstance(values[n], int) and not isinstance(values[n], bool):
                values[n] = float(values[n])
        return cls(**values)


def _check_bool(name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise ProtocolError(f"{name} must be bool, got {type(value).__name__}")


def _check_int(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{name} must be int, got {type(value).__name__}")


def _check_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{name} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ProtocolError(f"{name} must be finite, got {value}")
