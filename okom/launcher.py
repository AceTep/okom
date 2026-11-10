"""OKOM launcher: one window to calibrate, start and stop.

    python -m okom

The launcher only starts the two programs, `app.main` and `gaze.main`, as
separate processes, exactly as they run from the terminal, so the
architecture (two processes talking over UDP) stays the same. Stop sends
SIGTERM, on which both clean up (camera setting, window dimming).
"""

from __future__ import annotations

import logging
import os
import signal
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, QRegularExpression, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QPainter,
    QPixmap,
    QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from gaze.selection import read_recordings
from okom.commands import (
    MODEL_FILE,
    QUALITY_COLOR,
    REPO_ROOT,
    Command,
    any_calibration,
    calibrate_command,
    can_share_camera,
    chosen_calibration,
    describe_age,
    describe_quality,
    known_conditions,
    start_commands,
)
from shared.logs import LOG_DIR, setup_logging
from shared.screens import order_screens

log = logging.getLogger("okom")

STOP_TIMEOUT_MS = 5000  # SIGTERM first; SIGKILL only if a process does not exit by then
OK, BAD = "✓", "✗"


def make_icon() -> QIcon:
    """A simple eye, drawn so no image file is needed."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(80, 160, 255))
    p.drawEllipse(4, 16, 56, 32)
    p.setBrush(QColor(255, 255, 255))
    p.drawEllipse(20, 20, 24, 24)
    p.setBrush(QColor(20, 20, 30))
    p.drawEllipse(26, 26, 12, 12)
    p.end()
    return QIcon(pix)


class Launcher(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OKOM")
        self.setWindowIcon(make_icon())
        self._procs: dict[str, QProcess] = {}
        self._mode = "idle"  # idle | calibrating | running | stopping
        self._calibration_before = None  # newest recording when Calibrate was pressed
        self._build_ui()
        self._build_tray()
        self._check_environment()
        self.refresh()

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        grid = QGridLayout()
        self.screens_label = QLabel()
        self.backend_label = QLabel()
        self.model_label = QLabel()
        self.calibration_label = QLabel()
        rows = [
            ("Screens", self.screens_label),
            ("Window focus", self.backend_label),
            ("Face model", self.model_label),
            ("Calibration", self.calibration_label),
        ]
        for r, (name, widget) in enumerate(rows):
            grid.addWidget(QLabel(f"<b>{name}</b>"), r, 0, Qt.AlignmentFlag.AlignTop)
            widget.setWordWrap(True)
            grid.addWidget(widget, r, 1)
        grid.setColumnStretch(1, 1)  # values right next to their labels

        self.condition = QComboBox()
        self.condition.setEditable(True)  # pick a preset or type a new label
        self.condition.addItems(known_conditions())
        self.condition.setCurrentText("normal")
        self.condition.setValidator(
            QRegularExpressionValidator(QRegularExpression("[a-z0-9_-]{0,32}"))
        )
        self.condition.setToolTip(
            "Conditions of the calibration: pick one or type a new label (a-z, 0-9, _ -)"
        )
        self.condition.currentTextChanged.connect(self.refresh)
        self.share_camera = QCheckBox("Share camera (OBS)")
        self.share_camera.setToolTip(
            "Run the camera through PipeWire (pw-v4l2), so OBS can record it"
        )
        if not can_share_camera():
            self.share_camera.setEnabled(False)
            self.share_camera.setToolTip("Needs pw-v4l2 (Fedora: sudo dnf install pipewire-v4l2)")

        self.calibrate_btn = QPushButton("Calibrate")
        self.calibrate_btn.clicked.connect(self.calibrate)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_or_stop)
        self.hide_btn = QPushButton("Hide to tray")
        self.hide_btn.clicked.connect(self.hide)

        controls = QGridLayout()
        controls.addWidget(QLabel("Condition"), 0, 0)
        controls.addWidget(self.condition, 0, 1)
        controls.addWidget(self.share_camera, 0, 2)
        controls.addWidget(self.calibrate_btn, 1, 0)
        controls.addWidget(self.start_btn, 1, 1)
        controls.addWidget(self.hide_btn, 1, 2)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.logs_dir_btn = QPushButton("Open logs")
        self.logs_dir_btn.setFlat(True)
        self.logs_dir_btn.setToolTip(f"Log files of every run: {LOG_DIR}")
        self.logs_dir_btn.clicked.connect(self.open_logs)
        self.log_btn = QPushButton("Show log ▸")
        self.log_btn.setFlat(True)
        self.log_btn.clicked.connect(self.toggle_log)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        self.log_view.setMinimumHeight(220)
        self.log_view.hide()

        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.logs_dir_btn)
        bottom.addWidget(self.log_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addSpacing(8)
        layout.addLayout(controls)
        layout.addLayout(bottom)
        layout.addWidget(self.log_view)
        self.setMinimumWidth(520)

    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.hide_btn.setEnabled(False)
            self.hide_btn.setToolTip("No system tray on this desktop")
            return
        self.tray = QSystemTrayIcon(make_icon(), self)
        menu = QMenu()
        show = QAction("Show", menu)
        show.triggered.connect(self.show_window)
        self.tray_start = QAction("Start", menu)
        self.tray_start.triggered.connect(self.start_or_stop)
        quit_ = QAction("Quit", menu)
        quit_.triggered.connect(self.close)
        menu.addActions([show, self.tray_start, quit_])
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
            )
        )
        self.tray.show()

    def show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))

    def toggle_log(self) -> None:
        visible = not self.log_view.isVisible()
        self.log_view.setVisible(visible)
        self.log_btn.setText("Hide log ▾" if visible else "Show log ▸")
        self.adjustSize()

    # ---- state ------------------------------------------------------------

    def _check_environment(self) -> None:
        screens = order_screens(
            QGuiApplication.screens(), key=lambda s: (s.name(), s.geometry().x(), s.geometry().y())
        )
        self.screen_names = [s.name() for s in screens]
        self.screens_label.setText(
            "  ·  ".join(f"{i}: {name}" for i, name in enumerate(self.screen_names))
            + ("" if len(screens) > 1 else f"   {BAD} need at least 2")
        )
        from app.backends.detect import create_backend

        backend = create_backend()
        reason = getattr(backend, "reason", "")
        self.backend_ok = backend.name != "dummy"
        backend.close()
        self.backend_label.setText(
            f"{OK} {backend.name}" if self.backend_ok else f"{BAD} not available: {reason}"
        )
        self.model_ok = MODEL_FILE.exists()
        self.model_label.setText(
            f"{OK} {MODEL_FILE.name}"
            if self.model_ok
            else f"{BAD} missing, run: python scripts/download_models.py"
        )

    def refresh(self) -> None:
        condition = self.condition.currentText()
        self.calibration = chosen_calibration(condition) if condition else None
        if not condition:
            self.calibration_label.setText(f"{BAD} enter a condition")
        elif self.calibration is None and any_calibration(condition):
            self.calibration_label.setText(
                f"{BAD} every calibration for “{condition}” is unusable, calibrate again"
            )
        elif self.calibration is None:
            self.calibration_label.setText(f"{BAD} none for “{condition}”, calibrate first")
        else:
            c = self.calibration
            note = ""
            if c.screens != self.screen_names:
                note = f"<br>⚠ recorded with screens {', '.join(c.screens)}, calibrate again"
            if c.quality and c.quality.get("verdict") != "good":
                note += f"<br>{c.quality.get('message', '')}"
            if c.only_weak:
                note += "<br>only weak calibrations for this condition"
            for started, verdict in c.skipped:
                note += f"<br>newer one from {describe_age(started)} is {verdict}, not used"
            quality, color = describe_quality(c.quality)
            if color:
                quality = f"<span style='color:{color}'>{quality}</span>"
            mark = OK if c.usable else BAD
            when = describe_age(c.started)
            self.calibration_label.setText(f"{mark} {c.condition}, {when}, {quality}{note}")

        busy = self._mode != "idle"
        self.condition.setEnabled(not busy)
        self.share_camera.setEnabled(not busy and can_share_camera())
        self.calibrate_btn.setEnabled(not busy and self.model_ok and bool(condition))
        can_start = self.model_ok and self.calibration is not None and self.calibration.usable
        self.start_btn.setEnabled(self._mode == "running" or (not busy and can_start))
        self.start_btn.setText("Stop" if self._mode == "running" else "Start")
        if self.tray is not None:
            self.tray_start.setText(self.start_btn.text())
            self.tray_start.setEnabled(self.start_btn.isEnabled())
            self.tray.setToolTip(f"OKOM: {self._mode}")
        self.status.setText(
            {
                "idle": "Ready." if can_start else "Calibrate before starting.",
                "calibrating": "Calibrating: follow the dot on each screen (Esc aborts).",
                "running": "Running: look at a screen to give it keyboard focus.",
                "stopping": "Stopping…",
            }[self._mode]
        )

    # ---- processes --------------------------------------------------------

    def calibrate(self) -> None:
        self._calibration_before = self._newest_recording()
        self._mode = "calibrating"
        self._run(calibrate_command(self.condition.currentText(), self.share_camera.isChecked()))
        self.refresh()

    def start_or_stop(self) -> None:
        if self._mode == "running":
            self.stop()
            return
        if self._mode != "idle" or not self.start_btn.isEnabled():
            return
        self._mode = "running"
        for cmd in start_commands(self.calibration.path, self.share_camera.isChecked()):
            self._run(cmd)
        self.refresh()

    def stop(self) -> None:
        if not self._procs:
            return
        self._mode = "stopping"
        self.refresh()
        for proc in self._procs.values():
            proc.terminate()  # SIGTERM: both programs clean up on it
        QTimer.singleShot(STOP_TIMEOUT_MS, self._kill_leftovers)

    def _kill_leftovers(self) -> None:
        for label, proc in list(self._procs.items()):
            if proc.state() != QProcess.ProcessState.NotRunning:
                self._log(label, "did not stop in time, killing it")
                proc.kill()

    def _run(self, cmd: Command) -> None:
        proc = QProcess(self)
        proc.setWorkingDirectory(str(REPO_ROOT))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")  # live log lines
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda: self._read(cmd.label, proc))
        proc.finished.connect(lambda code, _status: self._finished(cmd.label, code))
        proc.errorOccurred.connect(
            lambda err: self._log(cmd.label, f"could not run {cmd.program}: {err.name}")
        )
        self._procs[cmd.label] = proc
        command_line = " ".join([cmd.program, *cmd.args])
        log.info("start %s: %s", cmd.label, command_line)
        self._log(cmd.label, "$ " + command_line)
        proc.start(cmd.program, cmd.args)

    def _read(self, label: str, proc: QProcess) -> None:
        text = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        for line in text.splitlines():
            if line.strip():
                self._log(label, line)

    def _finished(self, label: str, code: int) -> None:
        self._procs.pop(label, None)
        log.info("%s exited with code %d (mode %s)", label, code, self._mode)
        self._log(label, f"exited with code {code}")
        if self._mode == "calibrating":
            self._mode = "idle"
            if code != 0:
                self._error(f"Calibration failed (exit code {code}), see the log.")
                return
            self._refresh_conditions()
            self.refresh()
            self._report_calibration()
            return
        elif self._mode == "running":
            # one of the two died on its own: stop the other, it is useless alone
            self._error(f"{label} stopped unexpectedly (exit code {code}), see the log.")
            self.stop()
            return
        elif self._mode == "stopping" and not self._procs:
            self._mode = "idle"
        self.refresh()

    def _refresh_conditions(self) -> None:
        current = self.condition.currentText()
        self.condition.blockSignals(True)
        self.condition.clear()
        self.condition.addItems(known_conditions())
        self.condition.setCurrentText(current)
        self.condition.blockSignals(False)

    def _newest_recording(self):
        condition = self.condition.currentText()
        mine = [r for r in read_recordings() if r.condition == condition]
        return mine[-1] if mine else None

    def _report_calibration(self) -> None:
        """Tell the user right away whether the calibration just made is any good.

        Looks at the newest recording, not the chosen one: a weak new calibration
        leaves an older good one in use, and the user must still hear about it.
        """
        new = self._newest_recording()
        before = self._calibration_before
        if new is None or (before is not None and new.path == before.path):
            self.status.setText("Calibration aborted, nothing saved.")
            return
        quality = new.meta.get("quality")
        if quality is None:
            self.status.setText("Calibration saved.")
            return
        verdict = quality.get("verdict")
        color = QUALITY_COLOR.get(verdict, "")
        text = {
            "good": "Calibration saved and good",
            "weak": "Calibration saved but weak",
            "unusable": "Calibration not usable",
        }.get(verdict, "Calibration saved")
        kept = ""
        if verdict != "good" and self.calibration and self.calibration.path != new.path:
            kept = f" Still using the one from {describe_age(self.calibration.started)}."
        self.status.setText(
            f"<span style='color:{color}'>{text}: {quality.get('message', '')}{kept}</span>"
        )
        if verdict != "good":
            self.show_window()

    def _error(self, message: str) -> None:
        self.refresh()
        self.status.setText(f"<span style='color:#d33'>{message}</span>")
        if not self.log_view.isVisible():
            self.toggle_log()
        self.show_window()

    def _log(self, label: str, line: str) -> None:
        self.log_view.appendPlainText(f"[{label}] {line}")

    # ---- quitting ---------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Closing the window quits OKOM; running programs are stopped first."""
        for proc in self._procs.values():
            proc.terminate()
        for proc in self._procs.values():
            if not proc.waitForFinished(STOP_TIMEOUT_MS):
                proc.kill()
                proc.waitForFinished(1000)
        if self.tray is not None:
            self.tray.hide()
        event.accept()
        QApplication.quit()


def main() -> None:
    setup_logging("launcher", "%(asctime)s %(message)s")
    os.chdir(REPO_ROOT)
    app = QApplication(sys.argv)
    app.setApplicationName("OKOM")
    app.setDesktopFileName("okom")
    app.setQuitOnLastWindowClosed(False)  # hiding to the tray must not quit
    window = Launcher()
    window.show()
    # Ctrl+C in the terminal: same as closing the window (only sets a flag; see gaze/overlay.py)
    stop = {"requested": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(requested=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(requested=True))
    timer = QTimer()
    timer.timeout.connect(lambda: window.close() if stop["requested"] else None)
    timer.start(100)
    sys.exit(app.exec())
