"""Record calibration sessions and load them back.

A session is stored as a directory in data/calibration/:

    20261110-203753_normal/
        meta.json     condition, screens, config used, sample counts
        samples.npz   one row per labelled sample: target + raw MediaPipe output

Only landmarks, blendshapes and the head transform are stored, never images.
That is enough to recompute any feature later without recording again, and a
face image cannot be rebuilt from it.

    python -m gaze.calibration --condition normal
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from gaze.config import GazeConfig
from gaze.features import Face, Features, extract
from gaze.session import SessionResult
from shared.logs import setup_logging
from shared.signals import sigterm_as_keyboard_interrupt

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "calibration"
FORMAT_VERSION = 1


@dataclass
class Recording:
    """A loaded session: one entry per labelled sample (arrays of equal length)."""

    path: Path
    meta: dict
    t: np.ndarray  # (N,) capture time
    screen: np.ndarray  # (N,) target screen index
    x: np.ndarray  # (N,) target point within the screen, 0..1
    y: np.ndarray
    point: np.ndarray  # (N,) 1-based point number within its screen
    users: np.ndarray  # (N,) faces in the frame
    has_face: np.ndarray  # (N,) bool
    points: np.ndarray  # (N, 478, 2) landmarks in pixels (zeros where has_face is False)
    blendshapes: np.ndarray  # (N, B)
    matrix: np.ndarray  # (N, 4, 4)

    @property
    def condition(self) -> str:
        return self.meta["condition"]

    def face(self, i: int) -> Face | None:
        if not self.has_face[i]:
            return None
        names = self.meta["blendshape_names"]
        return Face(
            points=self.points[i].astype(np.float64),
            blendshapes=dict(zip(names, map(float, self.blendshapes[i]), strict=True)),
            matrix=self.matrix[i].astype(np.float64),
        )

    def features(self) -> list[Features | None]:
        return [None if f is None else extract(f) for f in map(self.face, range(len(self.t)))]


def save(result: SessionResult, cfg: GazeConfig, condition: str, out_dir: Path = DATA_DIR) -> Path:
    labelled = result.labelled()
    if not labelled:
        raise ValueError("no labelled samples to save")
    faces = [s.face for _, s in labelled]
    names = sorted(next((f.blendshapes for f in faces if f is not None), {}))
    n = len(labelled)
    points = np.zeros((n, 478, 2), np.float32)
    blend = np.zeros((n, len(names)), np.float32)
    matrix = np.zeros((n, 4, 4), np.float32)
    for i, f in enumerate(faces):
        if f is not None:
            points[i] = f.points
            blend[i] = [f.blendshapes[k] for k in names]
            matrix[i] = f.matrix

    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(result.timeline[0].start))
    path = out_dir / f"{stamp}_{condition}"
    path.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(
        path / "samples.npz",
        t=np.array([s.t for _, s in labelled]),
        screen=np.array([tg.screen for tg, _ in labelled], np.int16),
        x=np.array([tg.x for tg, _ in labelled], np.float32),
        y=np.array([tg.y for tg, _ in labelled], np.float32),
        point=np.array([tg.number for tg, _ in labelled], np.int16),
        users=np.array([s.users for _, s in labelled], np.int16),
        has_face=np.array([f is not None for f in faces]),
        points=points,
        blendshapes=blend,
        matrix=matrix,
    )
    meta = {
        "format_version": FORMAT_VERSION,
        "condition": condition,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(result.timeline[0].start)),
        "screens": [
            {"index": i, "name": g[0], "x": g[1], "y": g[2], "w": g[3], "h": g[4]}
            for i, g in enumerate(result.screens)
        ],
        "samples": n,
        "samples_with_face": int(sum(f is not None for f in faces)),
        "frames_total": len(result.samples),
        "blendshape_names": names,
        "config": {
            "camera": dataclasses.asdict(cfg.camera),
            "landmarks": dataclasses.asdict(cfg.landmarks),
            "calibration": dataclasses.asdict(cfg.calibration),
        },
    }
    (path / "meta.json").write_text(json.dumps(meta, indent=2))
    log.info("saved %d samples (%d with a face) to %s", n, meta["samples_with_face"], path)
    return path


def load(path: Path | str) -> Recording:
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())
    if meta.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"{path}: unsupported format version {meta.get('format_version')}")
    with np.load(path / "samples.npz") as z:
        arrays = {k: z[k] for k in z.files}
    return Recording(path=path, meta=meta, **arrays)


def list_recordings(data_dir: Path = DATA_DIR) -> list[Path]:
    if not data_dir.exists():
        return []
    return sorted(p for p in data_dir.iterdir() if (p / "meta.json").exists())


def main() -> None:
    import argparse

    from gaze.config import load_config
    from gaze.session import run_session

    setup_logging("calibration", "%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Record a calibration session.")
    parser.add_argument(
        "--condition",
        required=True,
        help="short label for the recording conditions, e.g. normal, glasses, dim",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", args.condition):
        parser.error("condition: lowercase letters, digits, '_' or '-', at most 32 characters")

    sigterm_as_keyboard_interrupt()  # Stop in the launcher must restore the camera too
    cfg = load_config()
    try:
        result = run_session(cfg, predict=prior_model(cfg, args.condition))
    except KeyboardInterrupt:
        log.error("aborted, nothing saved")
        return
    if not result.completed:
        log.error("aborted, nothing saved")
        return
    path = save(result, cfg, args.condition)
    quality = record_quality(path, cfg)
    level = {"good": logging.INFO, "weak": logging.WARNING}.get(quality.verdict, logging.ERROR)
    log.log(level, "calibration quality: %s, %s", quality.verdict.upper(), quality.message)


def prior_model(cfg: GazeConfig, condition: str, data_dir: Path = DATA_DIR):
    """predict() from the newest good calibration with the same screens, or None.

    Used during a new calibration to notice when the user looks at the wrong
    screen. Prefers the same condition; a weak or unusable calibration is never
    used, because its mistakes would look like the user's.
    """
    if not cfg.calibration.wrong_screen_check:
        return None

    from PySide6.QtWidgets import QApplication

    from gaze.models import train_predictor
    from gaze.overlay import ordered_qt_screens

    QApplication.instance() or QApplication(sys.argv)
    path = pick_prior(
        list_recordings(data_dir), [s.name() for s in ordered_qt_screens()], condition
    )
    if path is None:
        log.info("no earlier good calibration with these screens: wrong-screen check off")
        return None
    m = cfg.model
    predictor, _ = train_predictor(
        load(path), m.kind, m.feature_set, cfg.features.blink_threshold, m.softness_deg
    )
    log.info("wrong-screen check uses %s", path.name)
    return predictor.predict


def pick_prior(paths: list[Path], screens: list[str], condition: str) -> Path | None:
    """Newest recording rated good and made with these screens; same condition first."""
    same, other = [], []
    for path in reversed(paths):  # newest first
        try:
            meta = json.loads((path / "meta.json").read_text())
        except (OSError, ValueError):
            continue
        if meta.get("quality", {}).get("verdict") != "good":
            continue
        if [s["name"] for s in meta.get("screens", [])] != screens:
            continue
        (same if meta.get("condition") == condition else other).append(path)
    return (same or other or [None])[0]


def record_quality(path: Path, cfg: GazeConfig):
    """Assess a saved recording with the configured model and store the result in meta.json."""
    from gaze.models import assess

    rec = load(path)
    quality = assess(
        rec,
        cfg.model.kind,
        cfg.model.feature_set,
        cfg.features.blink_threshold,
        cfg.calibration.good_accuracy,
    )
    rec.meta["quality"] = quality.as_dict()
    (path / "meta.json").write_text(json.dumps(rec.meta, indent=2))
    return quality


if __name__ == "__main__":
    main()
