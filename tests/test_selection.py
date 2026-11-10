"""Which calibration is used (gaze/selection.py): one rule for gaze.main and the launcher."""

import json

from gaze.selection import choose, pick_prior, read_recordings

SCREENS = ["HDMI-A-1", "eDP-1"]


def rec(root, name, condition, verdict, screens=SCREENS):
    d = root / name
    d.mkdir()
    meta = {
        "condition": condition,
        "started": f"2026-11-10T{name[:2]}:00:00",
        "screens": [{"name": s} for s in screens],
    }
    if verdict is not None:
        meta["quality"] = {"verdict": verdict}
    (d / "meta.json").write_text(json.dumps(meta))


def test_newest_good_wins_and_newer_weak_is_reported(tmp_path) -> None:
    rec(tmp_path, "10_normal", "normal", "good")
    rec(tmp_path, "11_normal", "normal", "good")
    rec(tmp_path, "12_normal", "normal", "weak")
    rec(tmp_path, "13_normal", "normal", "unusable")
    c = choose(read_recordings(tmp_path), "normal")
    assert c.recording.path.name == "11_normal" and not c.weak
    assert [r.path.name for r in c.skipped] == ["13_normal", "12_normal"]


def test_unrated_old_recordings_count_as_good(tmp_path) -> None:
    rec(tmp_path, "10_normal", "normal", None)
    assert choose(read_recordings(tmp_path), "normal").recording.path.name == "10_normal"


def test_only_weak_falls_back_to_newest_weak(tmp_path) -> None:
    rec(tmp_path, "10_dim", "dim", "weak")
    rec(tmp_path, "11_dim", "dim", "weak")
    rec(tmp_path, "12_dim", "dim", "unusable")
    c = choose(read_recordings(tmp_path), "dim")
    assert c.recording.path.name == "11_dim" and c.weak
    assert [r.path.name for r in c.skipped] == ["12_dim"]


def test_nothing_usable(tmp_path) -> None:
    rec(tmp_path, "10_dim", "dim", "unusable")
    recs = read_recordings(tmp_path)
    assert choose(recs, "dim") is None and choose(recs, "normal") is None


def test_condition_none_means_any(tmp_path) -> None:
    rec(tmp_path, "10_normal", "normal", "good")
    rec(tmp_path, "11_glasses", "glasses", "good")
    assert choose(read_recordings(tmp_path)).recording.path.name == "11_glasses"


def test_unreadable_recordings_are_skipped(tmp_path) -> None:
    (tmp_path / "10_broken").mkdir()
    (tmp_path / "11_bad").mkdir()
    (tmp_path / "11_bad" / "meta.json").write_text("{not json")
    rec(tmp_path, "12_normal", "normal", "good")
    assert [r.path.name for r in read_recordings(tmp_path)] == ["12_normal"]


def test_pick_prior_never_uses_weak_or_unrated(tmp_path) -> None:
    rec(tmp_path, "10_normal", "normal", "good")
    rec(tmp_path, "11_glasses", "glasses", "good")
    rec(tmp_path, "12_normal", "normal", "weak")
    rec(tmp_path, "13_normal", "normal", None)
    rec(tmp_path, "14_normal", "normal", "good", screens=["DP-1", "eDP-1"])
    recs = read_recordings(tmp_path)
    assert pick_prior(recs, SCREENS, "normal").path.name == "10_normal"
    assert pick_prior(recs, SCREENS, "dim").path.name == "11_glasses"
    assert pick_prior(recs, ["X"], "normal") is None
