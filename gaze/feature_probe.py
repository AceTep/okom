"""Check by hand whether the features tell the screens apart.

Live readout (twice a second), no images are saved or shown:

    python -m gaze.feature_probe

Guided comparison on a fullscreen overlay: follow the dot over every screen,
then get per-feature means and the separation d' between screen 0 and 1:

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


def compare(cfg: GazeConfig) -> None:
    """Guided test on the fullscreen overlay: every calibration point on every screen."""
    from gaze.session import run_session
    from gaze.targets import label_samples

    result = run_session(cfg)
    if not result.completed:
        log.error("aborted, nothing to compare")
        return
    labelled = label_samples(result.timeline, ((s.t, s) for s in result.samples))
    by_screen: dict[int, list[np.ndarray]] = {}
    no_face = blinks = 0
    for target, sample in labelled:
        if sample.face is None:
            no_face += 1
            continue
        f = extract(sample.face)
        if is_blinking(f, cfg.features.blink_threshold):
            blinks += 1
        else:
            by_screen.setdefault(target.screen, []).append(f.vector())
    log.info(
        "%d labelled samples, %d without a face, %d blinking (both skipped)",
        len(labelled), no_face, blinks,
    )  # fmt: skip
    for screen, rows in sorted(by_screen.items()):
        log.info("screen %d (%s): %d samples", screen, result.screens[screen][0], len(rows))
    if len(by_screen) < 2 or min(len(r) for r in by_screen.values()) < 5:
        log.error("not enough samples with a face, check lighting and camera position")
        return
    if len(by_screen) > 2:
        log.warning("more than two screens, comparing only screen 0 and screen 1")
    a, b = np.array(by_screen[0]), np.array(by_screen[1])
    d = separation(a, b)
    log.info("%-16s %10s %10s %8s", "feature", "screen 0", "screen 1", "d'")
    for i in np.argsort(-d):
        log.info(
            "%-16s %+10.3f %+10.3f %8.1f",
            FEATURE_NAMES[i], a[:, i].mean(), b[:, i].mean(), d[i],
        )  # fmt: skip
    log.info("d' > 2 separates well, > 4 very well (rows sorted by d')")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="Inspect gaze features from the camera.")
    parser.add_argument("--compare", action="store_true", help="guided test on all screens")
    args = parser.parse_args()

    cfg = load_config()
    if args.compare:
        compare(cfg)
        return
    with Camera(cfg.camera) as cam, LandmarkDetector(cfg.landmarks) as det:
        try:
            live(cfg, cam, det)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
