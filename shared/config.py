"""Strict YAML -> dataclass loading, used by both app/ and gaze/.

Unknown or missing keys are an error, so a typo in a YAML file fails loudly
instead of silently falling back to a default.
"""

from __future__ import annotations

import dataclasses
import typing
from pathlib import Path
from typing import Any, TypeVar

import yaml

T = TypeVar("T")
_SCALARS: dict[type, tuple[type, ...]] = {
    str: (str,),
    int: (int,),
    float: (int, float),
    bool: (bool,),
}


def load_dataclass(cls: type[T], path: Path | str) -> T:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return build(cls, raw, Path(path).name)


def build(cls: type[T], raw: Any, where: str) -> T:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: expected a mapping, got {raw!r}")
    hints = typing.get_type_hints(cls)
    names = [f.name for f in dataclasses.fields(cls)]
    unknown = sorted(set(raw) - set(names))
    missing = sorted(set(names) - set(raw))
    if unknown or missing:
        raise ValueError(f"{where}: unknown keys {unknown}, missing keys {missing}")
    values = {}
    for name in names:
        kind = hints[name]
        if dataclasses.is_dataclass(kind):
            values[name] = build(kind, raw[name], f"{where}.{name}")
        else:
            values[name] = _scalar(kind, raw[name], f"{where}.{name}")
    return cls(**values)


def _scalar(kind: type, value: Any, where: str) -> Any:
    allowed = _SCALARS.get(kind)
    if allowed is None:
        raise TypeError(f"{where}: unsupported field type {kind}")
    if kind is not bool and isinstance(value, bool) or not isinstance(value, allowed):
        raise ValueError(f"{where}: expected {kind.__name__}, got {value!r}")
    return kind(value)
