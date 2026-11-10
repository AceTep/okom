"""Webcam capture that always hands out the newest frame.

A background thread reads the camera at its full rate and keeps only the
latest frame. Processing takes the newest one; if processing is slower than
the camera, old frames are skipped instead of piling up in a queue, so the
image is never stale.

Diagnostic mode measures the real frame rate; it never saves or shows images:

    python -m gaze.camera --seconds 5
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np

from gaze.config import CameraConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Frame:
    image: np.ndarray  # BGR, height x width x 3
    t: float  # Unix time right after the frame was read
    index: int  # 1, 2, 3, ... in capture order; gaps mean skipped frames


class Capture(Protocol):
    """The part of cv2.VideoCapture we use (lets tests use a fake)."""

    def read(self) -> tuple[bool, Any]: ...
    def release(self) -> None: ...


def open_capture(cfg: CameraConfig) -> cv2.VideoCapture:
    api = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
    cap = cv2.VideoCapture(cfg.device, api)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open camera {cfg.device}")
    if cfg.fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*cfg.fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
    cap.set(cv2.CAP_PROP_FPS, cfg.fps)
    # Do NOT set CAP_PROP_BUFFERSIZE to 1: with a single driver buffer the
    # camera drops every other frame (measured: 30 -> 15 fps).
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode(errors="replace")
    log.info(
        "camera %d: requested %dx%d %s @ %d fps, driver reports %.0fx%.0f %s @ %.0f fps",
        cfg.device, cfg.width, cfg.height, cfg.fourcc or "default", cfg.fps,
        cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT), fourcc,
        cap.get(cv2.CAP_PROP_FPS),
    )  # fmt: skip
    return cap


class Camera:
    def __init__(
        self,
        cfg: CameraConfig,
        capture_factory: Callable[[CameraConfig], Capture] = open_capture,
        first_frame_timeout: float = 3.0,
    ) -> None:
        self._override = _fixed_framerate(cfg) if cfg.fixed_framerate else None
        try:
            self._cap = capture_factory(cfg)
        except Exception:
            if self._override is not None:
                self._override.restore()
            raise
        self._cond = threading.Condition()
        self._latest: Frame | None = None
        self._last_returned = 0
        self._captured = 0
        self._skipped = 0
        self._running = True
        self._thread = threading.Thread(target=self._grab_loop, name="camera", daemon=True)
        self._thread.start()

        first = self.read(timeout=first_frame_timeout)
        if first is None:
            self.close()
            raise RuntimeError(f"camera {cfg.device} opened but delivers no frames")
        h, w = first.image.shape[:2]
        if (w, h) != (cfg.width, cfg.height):
            log.warning(
                "camera gives %dx%d instead of the requested %dx%d", w, h, cfg.width, cfg.height
            )

    def read(self, timeout: float = 1.0) -> Frame | None:
        """Newest frame not returned before; waits up to timeout for one."""
        with self._cond:
            fresh = self._cond.wait_for(
                lambda: self._latest is not None and self._latest.index > self._last_returned,
                timeout=timeout,
            )
            if not fresh:
                return None
            frame = self._latest
            self._last_returned = frame.index
            return frame

    @property
    def skipped(self) -> int:
        """Frames captured but never returned because a newer one replaced them."""
        with self._cond:
            return self._skipped

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=2.0)
        self._cap.release()
        if self._override is not None:
            self._override.restore()
            self._override = None

    def __enter__(self) -> Camera:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _grab_loop(self) -> None:
        failing = False
        while self._running:
            ok, image = self._cap.read()
            if not ok:
                if not failing:
                    log.warning("camera stopped delivering frames")
                    failing = True
                time.sleep(0.05)
                continue
            if failing:
                log.info("camera is delivering frames again")
                failing = False
            t = time.time()
            with self._cond:
                if self._latest is not None and self._latest.index > self._last_returned:
                    self._skipped += 1  # replaced before anyone read it
                self._captured += 1
                self._latest = Frame(image, t, self._captured)
                self._cond.notify_all()


def _fixed_framerate(cfg: CameraConfig):
    """Stop the camera from lowering its frame rate in dim light (Linux only)."""
    if not sys.platform.startswith("linux"):
        log.info("camera.fixed_framerate is only supported on Linux, ignoring it")
        return None
    from gaze.v4l2 import EXPOSURE_DYNAMIC_FRAMERATE, ControlOverride

    try:
        override = ControlOverride(f"/dev/video{cfg.device}", EXPOSURE_DYNAMIC_FRAMERATE, 0)
    except OSError as exc:
        log.warning("could not fix the frame rate (%s), the camera may slow down in dim light", exc)
        return None
    log.info("fixed frame rate on (exposure_dynamic_framerate %d -> 0)", override.original)
    return override


def measure_fps(camera: Camera, seconds: float) -> tuple[float, float]:
    """Mean frame rate and the longest gap between frames (ms)."""
    times = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if camera.read() is not None:
            times.append(time.monotonic())
    if len(times) < 2:
        return 0.0, float("inf")
    gaps = np.diff(times)
    return (len(times) - 1) / (times[-1] - times[0]), float(gaps.max() * 1000)


if __name__ == "__main__":
    import argparse
    import dataclasses

    from gaze.config import load_config

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Open the camera and measure its frame rate.")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--device", type=int, help="override camera.device from the config")
    parser.add_argument(
        "--fixed-framerate", choices=["on", "off"], help="override camera.fixed_framerate"
    )
    args = parser.parse_args()

    cfg = load_config().camera
    if args.device is not None:
        cfg = dataclasses.replace(cfg, device=args.device)
    if args.fixed_framerate is not None:
        cfg = dataclasses.replace(cfg, fixed_framerate=args.fixed_framerate == "on")
    with Camera(cfg) as cam:
        fps, worst = measure_fps(cam, args.seconds)
    log.info("measured %.1f fps over %.0f s, longest gap %.0f ms", fps, args.seconds, worst)
