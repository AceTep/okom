"""What the launcher runs and shows, without any Qt (unit-tested)."""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CALIBRATION_DIR = REPO_ROOT / "data" / "calibration"
MODEL_FILE = REPO_ROOT / "models" / "face_landmarker.task"
CONDITION_RE = re.compile(r"[a-z0-9_-]{1,32}")


@dataclass(frozen=True, slots=True)
class Command:
    label: str  # shown in the log, e.g. "gaze"
    program: str
    args: list[str]


def python_module(label: str, module: str, *args: str, share_camera: bool = False) -> Command:
    """`python -m module args`, optionally through pw-v4l2 so OBS can use the camera too."""
    base = [sys.executable, "-m", module, *args]
    if share_camera:
        return Command(label, "pw-v4l2", base)
    return Command(label, base[0], base[1:])


def calibrate_command(condition: str, share_camera: bool) -> Command:
    return python_module(
        "calibration", "gaze.calibration", "--condition", condition, share_camera=share_camera
    )


def start_commands(condition: str, share_camera: bool) -> list[Command]:
    return [
        python_module("app", "app.main"),
        python_module("gaze", "gaze.main", "--condition", condition, share_camera=share_camera),
    ]


def can_share_camera() -> bool:
    return sys.platform.startswith("linux") and shutil.which("pw-v4l2") is not None


@dataclass(frozen=True, slots=True)
class CalibrationInfo:
    path: Path
    condition: str
    started: float  # Unix time
    samples_with_face: int
    screens: list[str]


def latest_calibration(condition: str, data_dir: Path = CALIBRATION_DIR) -> CalibrationInfo | None:
    """Newest recording with this condition, or None. Unreadable recordings are skipped."""
    if not data_dir.exists():
        return None
    for path in sorted(data_dir.glob(f"*_{condition}"), reverse=True):
        try:
            meta = json.loads((path / "meta.json").read_text())
            started = time.mktime(time.strptime(meta["started"], "%Y-%m-%dT%H:%M:%S"))
            return CalibrationInfo(
                path=path,
                condition=meta["condition"],
                started=started,
                samples_with_face=int(meta["samples_with_face"]),
                screens=[s["name"] for s in meta["screens"]],
            )
        except (OSError, KeyError, ValueError):
            continue
    return None


def describe_age(started: float, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if time.strftime("%Y-%m-%d", time.localtime(started)) == time.strftime(
        "%Y-%m-%d", time.localtime(now)
    ):
        return time.strftime("today %H:%M", time.localtime(started))
    days = max(1, round((now - started) / 86400))
    when = time.strftime("%d.%m. %H:%M", time.localtime(started))
    return f"{when} ({days} day{'s' if days != 1 else ''} ago)"
