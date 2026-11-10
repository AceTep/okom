"""Gaze engine: camera -> face -> features -> screen -> UDP message to app/.

    python -m gaze.main                       # model from the newest calibration
    python -m gaze.main --condition normal    # newest calibration with that condition
    python -m gaze.main --recording DIR       # model from a chosen calibration

The model is trained at start-up from a saved calibration (a fraction of a
second), so there is no separate model file that could get out of date.
x and y are sent as the screen centre for now; only the screen is estimated.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections import Counter
from pathlib import Path

from gaze.calibration import load
from gaze.camera import Camera
from gaze.config import GazeConfig, load_config
from gaze.features import extract, is_blinking, primary_face
from gaze.landmarks import LandmarkDetector
from gaze.models import ScreenPredictor, train_predictor
from gaze.selection import choose, read_recordings
from gaze.sender import GazeSender
from gaze.smoothing import OneEuroFilter
from shared.logs import setup_logging
from shared.protocol import GazeMessage
from shared.signals import sigterm_as_keyboard_interrupt

log = logging.getLogger("gaze.main")

_STATUS_EVERY_S = 2.0


def build_message(
    t: float,
    users: int,
    vector,
    blink: bool,
    predictor: ScreenPredictor,
    unsure_below: float,
) -> GazeMessage:
    """Protocol message for one frame. vector is None when no face was found."""
    if vector is None:
        return GazeMessage(
            t=t, face=False, users=users, screen=None, x=0.5, y=0.5, conf=0.0, blink=False
        )
    screen, conf = predictor.predict(vector)
    return GazeMessage(
        t=t,
        face=True,
        users=users,
        screen=screen if conf >= unsure_below else None,
        x=0.5,
        y=0.5,
        conf=conf,
        blink=blink,
    )


def _choose(condition: str | None) -> Path:
    """Newest good calibration (see gaze/selection.py), with a clear message if none."""
    recordings = read_recordings()
    choice = choose(recordings, condition)
    which = f"with condition {condition!r} " if condition else ""
    if choice is None:
        if any(condition in (None, r.condition) for r in recordings):
            raise SystemExit(f"every calibration {which}is unusable, calibrate again")
        raise SystemExit(
            f"no calibration {which}yet, record one: "
            f"python -m gaze.calibration --condition {condition or 'normal'}"
        )
    for r in choice.skipped:
        log.warning("not using %s: rated %s", r.path.name, r.verdict)
    if choice.weak:
        name = choice.recording.path.name
        log.warning("only weak calibrations %sexist, using %s anyway", which, name)
    return choice.recording.path


def make_predictor(
    cfg: GazeConfig, recording_path: Path | None, condition: str | None = None
) -> ScreenPredictor:
    if recording_path is None:
        recording_path = _choose(condition)
    rec = load(recording_path)
    m = cfg.model
    try:
        predictor, data = train_predictor(
            rec, m.kind, m.feature_set, cfg.features.blink_threshold, m.softness_deg
        )
    except ValueError as exc:
        raise SystemExit(f"cannot use calibration {exc}; calibrate again") from None
    train_acc = float((predictor.model.predict(data.x) == data.screen).mean())
    detail = (
        f"pitch threshold {predictor.model.threshold_:.1f} deg"
        if cfg.model.kind == "threshold"
        else f"features {cfg.model.feature_set}"
    )
    log.info(
        "model %s (%s) trained on %s: %d samples, training accuracy %.1f %%",
        cfg.model.kind, detail, rec.path.name, len(data.screen), 100 * train_acc,
    )  # fmt: skip
    return predictor


def run(cfg: GazeConfig, predictor: ScreenPredictor) -> None:
    sender = GazeSender(cfg.udp.host, cfg.udp.port)
    smooth = (
        OneEuroFilter(cfg.smoothing.min_cutoff_hz, cfg.smoothing.beta, cfg.smoothing.d_cutoff_hz)
        if cfg.smoothing.enabled
        else None
    )
    log.info(
        "sending to udp://%s:%d, smoothing %s",
        cfg.udp.host, cfg.udp.port, "on" if smooth else "off",
    )  # fmt: skip
    screens: Counter = Counter()
    frames, last_status, detect_ms = 0, time.monotonic(), 0.0
    with Camera(cfg.camera) as cam, LandmarkDetector(cfg.landmarks) as det:
        try:
            while True:
                frame = cam.read(timeout=1.0)
                if frame is None:
                    log.warning("no frame from the camera for 1 s")
                    continue
                t0 = time.perf_counter()
                faces = det.detect(frame)
                detect_ms += (time.perf_counter() - t0) * 1000
                face = primary_face(faces)
                vector, blink = None, False
                if face is not None:
                    f = extract(face)
                    blink = is_blinking(f, cfg.features.blink_threshold)
                    vector = f.vector()
                    if smooth is not None:
                        vector = smooth(frame.t, vector)
                elif smooth is not None:
                    smooth.reset()
                msg = build_message(
                    frame.t, len(faces), vector, blink, predictor, cfg.model.unsure_below
                )
                sender.send(msg)
                frames += 1
                screens["none" if not msg.face else msg.screen] += 1

                now = time.monotonic()
                if now - last_status >= _STATUS_EVERY_S:
                    log.info(
                        "%.1f fps | mediapipe %.1f ms | screens %s | last conf %.2f | sent %d",
                        frames / (now - last_status), detect_ms / max(frames, 1),
                        dict(sorted(screens.items(), key=str)), msg.conf, sender.sent,
                    )  # fmt: skip
                    frames, last_status, detect_ms = 0, now, 0.0
                    screens.clear()
        except KeyboardInterrupt:
            pass
        finally:
            sender.close()


def main() -> None:
    setup_logging("gaze", "%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Run the gaze engine.")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--recording", type=Path, help="calibration to train on (default: newest)")
    which.add_argument("--condition", help="newest calibration with this condition, e.g. normal")
    args = parser.parse_args()
    sigterm_as_keyboard_interrupt()  # Stop in the launcher must restore the camera too
    cfg = load_config()
    run(cfg, make_predictor(cfg, args.recording, args.condition))


if __name__ == "__main__":
    main()
