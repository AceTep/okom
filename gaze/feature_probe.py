"""Check by hand whether the features tell the screens apart.

Live readout (twice a second), no images are saved or shown:

    python -m gaze.feature_probe

Guided comparison: look at the monitor, then at the laptop, and get per-feature
means and the separation d' between the two:

    python -m gaze.feature_probe --compare
"""

from __future__ import annotations

import argparse
import logging
import time

import numpy as np

from gaze.camera import Camera
from gaze.config import GazeConfig, load_config
from gaze.features import FEATURE_NAMES, extract, is_blinking, primary_face, separation
from gaze.landmarks import LandmarkDetector

log = logging.getLogger("gaze.feature_probe")


def live(cfg: GazeConfig, cam: Camera, det: LandmarkDetector) -> None:
    last_print = 0.0
    frames = 0
    detect_ms: list[float] = []
    while True:
        frame = cam.read()
        if frame is None:
            continue
        t0 = time.perf_counter()
        faces = det.detect(frame)
        detect_ms.append((time.perf_counter() - t0) * 1000)
        frames += 1
        now = time.monotonic()
        if now - last_print < 0.5:
            continue
        fps = frames / (now - last_print) if last_print else 0.0
        last_print, frames = now, 0
        face = primary_face(faces)
        timing = f"| mp {np.median(detect_ms):4.1f} ms | {fps:4.1f} fps | skipped {cam.skipped}"
        detect_ms.clear()
        if face is None:
            log.info("faces 0 %s", timing)
            continue
        f = extract(face)
        log.info(
            "faces %d | pitch %+6.1f yaw %+6.1f | iris v R %+.3f L %+.3f h R %.2f L %.2f"
            " | look up %.2f down %.2f | blink %s | z %5.1f cm %s",
            len(faces), f.pitch, f.yaw, f.iris_v_right, f.iris_v_left, f.iris_h_right,
            f.iris_h_left, f.look_up, f.look_down,
            "YES" if is_blinking(f, cfg.features.blink_threshold) else "no ", f.head_z, timing,
        )  # fmt: skip


def collect(
    cfg: GazeConfig, cam: Camera, det: LandmarkDetector, label: str, seconds: float
) -> np.ndarray:
    for n in (3, 2, 1):
        log.info(">>> Look at the %s, starting in %d ...", label, n)
        time.sleep(1)
    log.info(">>> Recording %s for %.0f s, keep looking, move your eyes around it", label, seconds)
    rows, no_face, blinks = [], 0, 0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        frame = cam.read()
        if frame is None:
            continue
        face = primary_face(det.detect(frame))
        if face is None:
            no_face += 1
            continue
        f = extract(face)
        if is_blinking(f, cfg.features.blink_threshold):
            blinks += 1
            continue
        rows.append(f.vector())
    log.info(
        "%s: %d samples (%d without a face, %d blinking skipped)", label, len(rows), no_face, blinks
    )
    return np.array(rows)


def compare(cfg: GazeConfig, cam: Camera, det: LandmarkDetector, seconds: float) -> None:
    monitor = collect(cfg, cam, det, "MONITOR (top)", seconds)
    laptop = collect(cfg, cam, det, "LAPTOP (bottom)", seconds)
    if len(monitor) < 5 or len(laptop) < 5:
        log.error("not enough samples with a face, check lighting and camera position")
        return
    d = separation(monitor, laptop)
    log.info("%-16s %10s %10s %8s", "feature", "monitor", "laptop", "d'")
    for i in np.argsort(-d):
        log.info(
            "%-16s %+10.3f %+10.3f %8.1f",
            FEATURE_NAMES[i], monitor[:, i].mean(), laptop[:, i].mean(), d[i],
        )  # fmt: skip
    log.info("d' > 2 separates well, > 4 very well (rows sorted by d')")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="Inspect gaze features from the camera.")
    parser.add_argument("--compare", action="store_true", help="guided monitor vs laptop test")
    parser.add_argument("--seconds", type=float, default=5.0, help="recording time per screen")
    args = parser.parse_args()

    cfg = load_config()
    with Camera(cfg.camera) as cam, LandmarkDetector(cfg.landmarks) as det:
        try:
            if args.compare:
                compare(cfg, cam, det, args.seconds)
            else:
                live(cfg, cam, det)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
