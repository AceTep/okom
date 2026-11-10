"""Run the on-screen guide while the camera records features in the background."""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from gaze.camera import Camera
from gaze.config import GazeConfig
from gaze.features import Face, extract, is_blinking, primary_face
from gaze.landmarks import LandmarkDetector
from gaze.targets import Interval, Step, Target, build_timeline, label_samples

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
    pauses: list[Interval] = field(default_factory=list)  # the dot waited (real time)
    excluded: list[Interval] = field(default_factory=list)  # wrong screen (real time)

    def labelled(self) -> list[tuple[Target, Sample]]:
        """Samples taken while a point was being recorded, minus pauses and exclusions."""
        return label_samples(
            self.timeline, ((s.t, s) for s in self.samples), self.pauses, self.excluded
        )


class _Recorder(threading.Thread):
    """Camera + landmarks in a background thread; the Qt UI owns the main thread."""

    def __init__(self, cfg: GazeConfig, predict: Callable | None = None) -> None:
        """predict(feature vector) -> (screen, confidence), from an earlier calibration."""
        super().__init__(name="recorder", daemon=True)
        self._cfg = cfg
        self._predict = predict
        self.prediction: tuple[float, int, float] | None = None  # (capture time, screen, conf)
        self.samples: list[Sample] = []
        self.ready = threading.Event()
        self.failed: str | None = None
        self._stop_event = threading.Event()
        self._ready_at = 0.0
        self._last_face: float | None = None  # capture time of the last frame with a face

    def seconds_without_face(self) -> float:
        """How long no face has been seen (since start if never). Read by the UI thread."""
        last = self._last_face if self._last_face is not None else self._ready_at
        return max(0.0, time.time() - last)

    def run(self) -> None:
        try:
            with Camera(self._cfg.camera) as cam, LandmarkDetector(self._cfg.landmarks) as det:
                self._ready_at = time.time()
                self.ready.set()
                while not self._stop_event.is_set():
                    frame = cam.read(timeout=0.5)
                    if frame is None:
                        continue
                    faces = det.detect(frame)
                    face = primary_face(faces)
                    if face is not None:
                        self._last_face = frame.t
                    self.samples.append(Sample(frame.t, face, len(faces)))
                    self.prediction = self._looking_at(frame.t, face)
        except Exception as exc:  # reported to the UI, which then stops
            log.exception("recorder failed")
            self.failed = str(exc)
            self.ready.set()

    def _looking_at(self, t: float, face: Face | None) -> tuple[float, int, float] | None:
        if self._predict is None or face is None:
            return None
        f = extract(face)
        if is_blinking(f, self._cfg.features.blink_threshold):
            return None
        screen, conf = self._predict(f.vector())
        return t, screen, conf

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=3.0)


def run_session(
    cfg: GazeConfig, screens: list[int] | None = None, predict: Callable | None = None
) -> SessionResult:
    """Guide the user over the given screens (default: all) and record features.

    With `predict` (a model from an earlier calibration) the guide notices when
    the user looks at the wrong screen and waits for them.
    """
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

    recorder = _Recorder(cfg, predict)
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
        c = cfg.calibration
        overlay = run_overlay(
            app,
            timeline,
            should_stop=lambda: recorder.failed is not None,
            face_missing=lambda: recorder.seconds_without_face() >= c.face_warning_s,
            looking_at=(lambda: recorder.prediction) if predict is not None else None,
            pause_on_problems=c.pause_on_problems,
            wrong_screen_after_s=c.wrong_screen_after_s,
            wrong_screen_conf=c.wrong_screen_conf,
            max_pause_s=c.max_pause_s,
        )
    finally:
        recorder.stop()
    return SessionResult(
        timeline,
        recorder.samples,
        overlay.completed and not recorder.failed,
        geometry,
        overlay.pauses,
        overlay.excluded,
    )
