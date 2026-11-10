"""Launcher logic without Qt: commands and calibration lookup."""

import json
import sys
import time

from okom.commands import (
    calibrate_command,
    describe_age,
    latest_calibration,
    python_module,
    start_commands,
)


def test_commands() -> None:
    cmd = calibrate_command("normal", share_camera=False)
    assert cmd.program == sys.executable
    assert cmd.args == ["-m", "gaze.calibration", "--condition", "normal"]
    app, gaze = start_commands("glasses", share_camera=True)
    assert app.program == sys.executable and app.args == [
        "-m",
        "app.main",
    ]  # app never needs the camera
    assert gaze.program == "pw-v4l2"
    assert gaze.args == [sys.executable, "-m", "gaze.main", "--condition", "glasses"]
    assert python_module("x", "m").label == "x"


def write_recording(root, name, started, condition, samples=500) -> None:
    d = root / name
    d.mkdir(parents=True)
    meta = {
        "condition": condition,
        "started": started,
        "samples_with_face": samples,
        "screens": [{"name": "HDMI-A-1"}, {"name": "eDP-1"}],
    }
    (d / "meta.json").write_text(json.dumps(meta))


def test_latest_calibration_per_condition(tmp_path) -> None:
    write_recording(tmp_path, "20261110-204709_normal", "2026-11-10T20:47:09", "normal")
    write_recording(tmp_path, "20261110-205000_naocale", "2026-11-10T20:50:00", "naocale")
    write_recording(tmp_path, "20261111-090000_normal", "2026-11-11T09:00:00", "normal", 300)
    (tmp_path / "20261112-000000_normal").mkdir()  # broken: no meta.json, skipped
    info = latest_calibration("normal", tmp_path)
    assert info.path.name == "20261111-090000_normal" and info.samples_with_face == 300
    assert info.screens == ["HDMI-A-1", "eDP-1"]
    assert latest_calibration("dim", tmp_path) is None
    assert latest_calibration("normal", tmp_path / "missing") is None


def test_describe_age() -> None:
    now = time.mktime(time.strptime("2026-11-10T21:00:00", "%Y-%m-%dT%H:%M:%S"))
    today = now - 3600
    assert describe_age(today, now) == "today 20:00"
    assert describe_age(now - 2 * 86400, now) == "08.11. 21:00 (2 days ago)"
