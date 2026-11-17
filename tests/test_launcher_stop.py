"""The Stop timer kills only what was being stopped (real processes, no window needed)."""

import sys

from PySide6.QtCore import QCoreApplication, QEventLoop, QProcess, QTimer

from okom.launcher import kill_later


def sleeper() -> QProcess:
    proc = QProcess()
    proc.start(sys.executable, ["-c", "import time; time.sleep(30)"])
    assert proc.waitForStarted(5000)
    return proc


def run_events(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_stop_timer_spares_a_process_started_after_stop() -> None:
    QCoreApplication.instance() or QCoreApplication([])
    stuck = sleeper()  # ignored SIGTERM, still running when the timer fires
    killed: list[str] = []
    kill_later({"gaze": stuck}, 200, killed.append)
    calibration = sleeper()  # user clicked Calibrate right after Stop
    try:
        run_events(600)
        assert killed == ["gaze"]
        assert stuck.state() == QProcess.ProcessState.NotRunning
        assert calibration.state() == QProcess.ProcessState.Running
    finally:
        for proc in (stuck, calibration):
            proc.kill()
            proc.waitForFinished(3000)


def test_stop_timer_quiet_when_everything_stopped() -> None:
    QCoreApplication.instance() or QCoreApplication([])
    done = sleeper()
    done.kill()
    assert done.waitForFinished(3000)
    killed: list[str] = []
    kill_later({"app": done}, 50, killed.append)
    run_events(200)
    assert killed == []
