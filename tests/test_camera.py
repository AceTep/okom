"""Camera frame handling with a fake capture device (no real camera needed)."""

import threading
import time

import numpy as np
import pytest

from gaze.camera import Camera
from gaze.config import CameraConfig

CFG = CameraConfig(device=0, width=4, height=3, fps=100, fourcc="", fixed_framerate=False)


class FakeCapture:
    """Delivers a tiny frame every `period` seconds, like a camera does."""

    def __init__(self, period: float = 0.005, fail: bool = False) -> None:
        self.period = period
        self.fail = fail
        self.released = threading.Event()

    def read(self):
        time.sleep(self.period)
        if self.fail:
            return False, None
        return True, np.zeros((3, 4, 3), np.uint8)

    def release(self) -> None:
        self.released.set()


def test_read_returns_increasing_fresh_frames() -> None:
    with Camera(CFG, lambda _: FakeCapture()) as cam:
        indices = [cam.read().index for _ in range(5)]
    assert indices == sorted(indices) and len(set(indices)) == 5


def test_slow_consumer_gets_newest_frame_and_skips_old() -> None:
    with Camera(CFG, lambda _: FakeCapture(period=0.002)) as cam:
        first = cam.read()
        time.sleep(0.1)  # processing is slower than the camera
        second = cam.read()
        assert second.index > first.index + 5  # jumped to a recent frame
        assert cam.skipped >= 5
        assert time.time() - second.t < 0.05  # and it is fresh, not stale


def test_read_times_out_without_new_frame() -> None:
    with Camera(CFG, lambda _: FakeCapture(period=0.3)) as cam:
        cam.read(timeout=1.0)
        assert cam.read(timeout=0.05) is None


def test_camera_without_frames_raises_and_releases() -> None:
    fake = FakeCapture(fail=True)
    with pytest.raises(RuntimeError, match="no frames"):
        Camera(CFG, lambda _: fake, first_frame_timeout=0.2)
    assert fake.released.is_set()


def test_native_stderr_capture_restores_fd() -> None:
    import os

    from gaze.landmarks import _captured_native_stderr

    with _captured_native_stderr() as out:
        os.write(2, b"native warning\n")
    assert out.text == "native warning"
    with pytest.raises(RuntimeError), _captured_native_stderr() as out:
        os.write(2, b"before failure\n")
        raise RuntimeError("boom")
    assert out.text == "before failure"  # captured even when the block fails
    os.write(2, b"")  # fd 2 is usable again


def test_recorder_counts_time_without_face() -> None:
    from gaze.session import _Recorder

    rec = _Recorder.__new__(_Recorder)  # no camera: only the bookkeeping
    rec._ready_at = time.time() - 2.0
    rec._last_face = None
    assert rec.seconds_without_face() == pytest.approx(2.0, abs=0.1)  # never seen: since start
    rec._last_face = time.time() - 0.2
    assert rec.seconds_without_face() == pytest.approx(0.2, abs=0.1)


def test_recorder_does_not_shadow_thread_internals() -> None:
    """Thread keeps private state (_started, _stop...); overwriting it broke start() twice."""
    import inspect
    import threading

    from gaze.session import _Recorder

    used = set()  # attribute names our own methods touch
    for _, fn in inspect.getmembers(_Recorder, inspect.isfunction):
        if fn.__qualname__.startswith("_Recorder."):
            used |= set(fn.__code__.co_names)
    names = set(vars(threading.Thread())) | set(vars(threading.Thread))
    thread_private = {n for n in names if n.startswith("_") and not n.startswith("__")}
    assert not used & thread_private
