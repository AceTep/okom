"""Screen classification accuracy from saved calibration recordings.

    python -m eval.screen_accuracy              # every recording in data/calibration
    python -m eval.screen_accuracy DIR [DIR..]  # chosen recordings

For each recording: leave-one-point-out accuracy of every model and feature
set, then per screen row for the best one. With two or more recordings, also
train on one and test on another (e.g. normal -> glasses).

Accuracy is per camera frame, before the app's dwell and hysteresis, so it is
a lower bound on how often focus would actually go to the wrong screen.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

from gaze.calibration import list_recordings, load
from gaze.config import load_config
from gaze.models import (
    FEATURE_SETS,
    MODELS,
    build_dataset,
    coverage_problem,
    leave_one_point_out,
    train_test,
)

log = logging.getLogger("eval.screen_accuracy")


def candidates():
    for model, (factory, fixed) in MODELS.items():
        sets = {"/".join(fixed): fixed} if fixed else FEATURE_SETS
        for set_name, names in sets.items():
            yield f"{model} [{set_name}]", factory, names


def usable(rec, blink: float) -> bool:
    """Log sample counts; False if the recording cannot be evaluated."""
    data = build_dataset([rec], ("pitch",), blink)
    total = len(rec.t)
    log.info(
        "  %d samples: %d used, %d without a face, %d blinking",
        total, len(data.screen), data.skipped_no_face, data.skipped_blink,
    )  # fmt: skip
    if data.skipped_no_face > 0.2 * total:
        log.warning("  more than 20 % of samples have no face: check lighting and camera")
    problem = coverage_problem(data)
    if problem:
        log.error("  cannot evaluate: %s", problem)
        return False
    return True


def per_recording(rec, blink: float) -> None:
    log.info("=== %s (condition %s)", rec.path.name, rec.condition)
    if not usable(rec, blink):
        return
    best = None
    for label, factory, names in candidates():
        data = build_dataset([rec], names, blink)
        pred = leave_one_point_out(data, factory)
        acc = float(np.mean(pred == data.screen))
        log.info("  %-36s %6.1f %%  (n=%d)", label, 100 * acc, len(pred))
        if best is None or acc > best[0]:
            best = (acc, label, data, pred)
    acc, label, data, pred = best
    log.info("  best: %s, per screen row (0 = top of the screen):", label)
    for screen in np.unique(data.screen):
        for row in np.unique(data.row[data.screen == screen]):
            m = (data.screen == screen) & (data.row == row)
            log.info(
                "    screen %d row %d: %6.1f %%  (n=%d)",
                screen, row, 100 * np.mean(pred[m] == data.screen[m]), m.sum(),
            )  # fmt: skip


def cross(recs, blink: float) -> None:
    recs = [r for r in recs if coverage_problem(build_dataset([r], ("pitch",), blink)) is None]
    if len(recs) < 2:
        return
    log.info("=== train on one recording, test on another")
    for label, factory, names in candidates():
        cells = []
        for a in recs:
            for b in recs:
                if a is b:
                    continue
                train, test = build_dataset([a], names, blink), build_dataset([b], names, blink)
                acc = float(np.mean(train_test(train, test, factory) == test.screen))
                cells.append(f"{a.condition}->{b.condition} {100 * acc:5.1f} %")
        log.info("  %-36s %s", label, " | ".join(cells))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("recordings", nargs="*", type=Path)
    args = parser.parse_args()
    paths = args.recordings or list_recordings()
    if not paths:
        raise SystemExit(
            "no recordings, record one with: python -m gaze.calibration --condition normal"
        )
    blink = load_config().features.blink_threshold
    recs = [load(p) for p in paths]
    for rec in recs:
        per_recording(rec, blink)
    if len(recs) > 1:
        cross(recs, blink)


if __name__ == "__main__":
    main()
