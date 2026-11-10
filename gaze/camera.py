"""Webcam capture with capture timestamps.

Diagnostic mode measures the real frame rate; it never saves or shows images:

    python -m gaze.camera --seconds 5
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass

import cv2
import numpy as np

from gaze.config import CameraConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Frame:
    image: np.ndarray  # BGR, height x width x 3
    t: float  # Unix time right after the frame was read
    index: int


class Camera:
    def __init__(self, cfg: CameraConfig) -> None:
        api = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(cfg.device, api)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open camera {cfg.device}")
        if cfg.fourcc:
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*cfg.fourcc))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        self._cap.set(cv2.CAP_PROP_FPS, cfg.fps)
        # Keep the driver queue short so we always process a fresh frame.
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._index = 0

        first = self.read()
        if first is None:
            self.close()
            raise RuntimeError(f"camera {cfg.device} opened but delivers no frames")
        h, w = first.image.shape[:2]
        fourcc = (
            int(self._cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode(errors="replace")
        )
        log.info(
            "camera %d: %dx%d %s, driver reports %.0f fps",
            cfg.device,
            w,
            h,
            fourcc,
            self._cap.get(cv2.CAP_PROP_FPS),
        )
        if (w, h) != (cfg.width, cfg.height):
            log.warning(
                "camera gave %dx%d instead of the requested %dx%d", w, h, cfg.width, cfg.height
            )

    def read(self) -> Frame | None:
        ok, image = self._cap.read()
        if not ok:
            return None
        self._index += 1
        return Frame(image, time.time(), self._index)

    def close(self) -> None:
        self._cap.release()

    def __enter__(self) -> Camera:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


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

    from gaze.config import load_config

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Open the camera and measure its frame rate.")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--device", type=int, help="override camera.device from the config")
    args = parser.parse_args()

    cfg = load_config().camera
    if args.device is not None:
        cfg = CameraConfig(args.device, cfg.width, cfg.height, cfg.fps, cfg.fourcc)
    with Camera(cfg) as cam:
        fps, worst = measure_fps(cam, args.seconds)
    log.info("measured %.1f fps over %.0f s, longest gap %.0f ms", fps, args.seconds, worst)
