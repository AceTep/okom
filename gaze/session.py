"""Run the on-screen guide while the camera records features in the background."""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass, field

from gaze.camera import Camera
from gaze.config import GazeConfig
from gaze.features import Face, primary_face
from gaze.landmarks import LandmarkDetector
from gaze.targets import Step, build_timeline

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Sample:
    t: float  # capture time of the frame
    face: Face | None  # raw landmarks of the primary face, None when no face was found
    users: int  # faces in the frame


@dataclass
class SessionResult:
    timeline: list[Step]
    samples: list[Sample]
    completed: bool  # False if aborted or the camera failed
    screens: list[tuple[str, int, int, int, int]] = field(default_factory=list)  # name, x, y, w, h


class _Recorder(threading.Thread):
    """Camera + landmarks in a background thread; the Qt UI owns the main thread."""

    def __init__(self, cfg: GazeConfig) -> None:
        super().__init__(name="recorder", daemon=True)
        self._cfg = cfg
        self.samples: list[Sample] = []
        self.ready = threading.Event()
        self.failed: str | None = None
        self._stop_event = threading.Event()

    def run(self) -> None:
        try:
            with Camera(self._cfg.camera) as cam, LandmarkDetector(self._cfg.landmarks) as det:
                self.ready.set()
                while not self._stop_event.is_set():
                    frame = cam.read(timeout=0.5)
                    if frame is None:
                        continue
                    faces = det.detect(frame)
                    self.samples.append(Sample(frame.t, primary_face(faces), len(faces)))
        except Exception as exc:  # reported to the UI, which then stops
            log.exception("recorder failed")
            self.failed = str(exc)
            self.ready.set()

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=3.0)


def run_session(cfg: GazeConfig, screens: list[int] | None = None) -> SessionResult:
    """Guide the user over the given screens (default: all) and record features."""
    from PySide6.QtWidgets import QApplication

    from gaze.overlay import ordered_qt_screens, run_overlay

    app = QApplication.instance() or QApplication(sys.argv)
    qt_screens = ordered_qt_screens()
    geometry = [
        (s.name(), s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height())
        for s in qt_screens
    ]
    for i, g in enumerate(geometry):
        log.info("screen %d = %s at %d,%d %dx%d", i, *g)
    order = list(range(len(qt_screens))) if screens is None else screens

    recorder = _Recorder(cfg)
    recorder.start()
    try:
        recorder.ready.wait(timeout=15.0)
    except KeyboardInterrupt:  # stopped while the camera was starting: still clean up
        recorder.stop()
        raise
    if recorder.failed or not recorder.ready.is_set():
        recorder.stop()
        raise RuntimeError(f"camera did not start: {recorder.failed or 'timeout'}")

    timeline = build_timeline(order, cfg.calibration, start=time.time() + 0.5)
    try:
        completed = run_overlay(app, timeline, should_stop=lambda: recorder.failed is not None)
    finally:
        recorder.stop()
    return SessionResult(timeline, recorder.samples, completed and not recorder.failed, geometry)
