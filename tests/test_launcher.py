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


def test_quality_in_calibration_info(tmp_path) -> None:
    from okom.commands import describe_quality

    write_recording(tmp_path, "20261110-204709_normal", "2026-11-10T20:47:09", "normal")
    info = latest_calibration("normal", tmp_path)
    assert info.quality is None and info.usable  # old recording: not measured, still usable
    meta_path = info.path / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["quality"] = {"verdict": "unusable", "accuracy": None, "message": "no face"}
    meta_path.write_text(json.dumps(meta))
    info = latest_calibration("normal", tmp_path)
    assert not info.usable
    assert describe_quality(info.quality) == ("unusable", "#d33")
    assert describe_quality({"verdict": "good", "accuracy": 0.996})[0] == "quality 99.6 %"
    assert describe_quality(None) == ("quality not measured", "")


def test_known_conditions(tmp_path) -> None:
    from okom.commands import PRESET_CONDITIONS, known_conditions

    write_recording(tmp_path, "20261110-205000_naocale", "2026-11-10T20:50:00", "naocale")
    write_recording(tmp_path, "20261110-204709_normal", "2026-11-10T20:47:09", "normal")
    (tmp_path / "20261111-000000_broken").mkdir()  # no meta.json: not offered
    names = known_conditions(tmp_path)
    assert names[: len(PRESET_CONDITIONS)] == list(PRESET_CONDITIONS)
    assert names[len(PRESET_CONDITIONS) :] == ["naocale"]  # recorded, not a duplicate preset
    assert known_conditions(tmp_path / "missing") == list(PRESET_CONDITIONS)
