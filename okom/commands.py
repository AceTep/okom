"""What the launcher runs and shows, without any Qt (unit-tested)."""

from __future__ import annotations

import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from gaze.selection import CALIBRATION_DIR, choose, read_recordings

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_FILE = REPO_ROOT / "models" / "face_landmarker.task"
CONDITION_RE = re.compile(r"[a-z0-9_-]{1,32}")
# Offered in the launcher; any other label can still be typed (e.g. "classroom").
PRESET_CONDITIONS = ("normal", "glasses", "dim", "bright", "posture")


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


def start_commands(recording: Path, share_camera: bool) -> list[Command]:
    """The exact recording shown in the launcher is the one gaze.main trains on."""
    return [
        python_module("app", "app.main"),
        python_module(
            "gaze", "gaze.main", "--recording", str(recording), share_camera=share_camera
        ),
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
    quality: dict | None  # gaze.models.Quality.as_dict(), None for old recordings
    only_weak: bool = False  # chosen although weak: nothing better for this condition
    skipped: tuple[tuple[float, str], ...] = ()  # newer recordings not used: (started, verdict)

    @property
    def usable(self) -> bool:
        return self.quality is None or self.quality.get("verdict") != "unusable"


def _unix(started: str) -> float:
    return time.mktime(time.strptime(started, "%Y-%m-%dT%H:%M:%S"))


def chosen_calibration(condition: str, data_dir: Path = CALIBRATION_DIR) -> CalibrationInfo | None:
    """The calibration Start will use (rule in gaze/selection.py), or None."""
    choice = choose(read_recordings(data_dir), condition)
    if choice is None:
        return None
    r = choice.recording
    try:
        return CalibrationInfo(
            path=r.path,
            condition=r.condition,
            started=_unix(r.started),
            samples_with_face=int(r.meta["samples_with_face"]),
            screens=r.screens,
            quality=r.meta.get("quality"),
            only_weak=choice.weak,
            skipped=tuple((_unix(x.started), x.verdict or "?") for x in choice.skipped),
        )
    except (KeyError, ValueError):
        return None


def any_calibration(condition: str, data_dir: Path = CALIBRATION_DIR) -> bool:
    return any(r.condition == condition for r in read_recordings(data_dir))


def describe_age(started: float, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if time.strftime("%Y-%m-%d", time.localtime(started)) == time.strftime(
        "%Y-%m-%d", time.localtime(now)
    ):
        return time.strftime("today %H:%M", time.localtime(started))
    days = max(1, round((now - started) / 86400))
    when = time.strftime("%d.%m. %H:%M", time.localtime(started))
    return f"{when} ({days} day{'s' if days != 1 else ''} ago)"


QUALITY_COLOR = {"good": "#2a2", "weak": "#c80", "unusable": "#d33"}


def describe_quality(quality: dict | None) -> tuple[str, str]:
    """(short text, colour) for the calibration status line."""
    if quality is None:
        return "quality not measured", ""
    verdict = quality.get("verdict", "?")
    accuracy = quality.get("accuracy")
    short = f"quality {100 * accuracy:.1f} %" if accuracy is not None else "unusable"
    return short, QUALITY_COLOR.get(verdict, "")


def known_conditions(data_dir: Path = CALIBRATION_DIR) -> list[str]:
    """Presets first, then every other condition that already has a recording."""
    recorded = set()
    if data_dir.exists():
        for path in data_dir.iterdir():
            _, _, condition = path.name.partition("_")
            if CONDITION_RE.fullmatch(condition) and (path / "meta.json").exists():
                recorded.add(condition)
    return list(PRESET_CONDITIONS) + sorted(recorded - set(PRESET_CONDITIONS))
