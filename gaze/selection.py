"""Which calibration to use: one rule for gaze.main, the launcher and the calibration.

Reads only each recording's meta.json (no numpy, no camera, no MediaPipe), so
the launcher can use it without loading the gaze engine.

The rule: the newest recording rated good. Recordings from before quality was
measured count as good. If a condition only has weak recordings, the newest
weak one is used, flagged as such. Unusable recordings are never used. Older
recordings are not preferred just for a higher score: scores of different
recordings are not comparable (each rates itself), and the newest best
reflects the current light and posture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CALIBRATION_DIR = Path(__file__).resolve().parent.parent / "data" / "calibration"


@dataclass(frozen=True, slots=True)
class RecordingInfo:
    path: Path
    condition: str
    started: str  # ISO local time, e.g. 2026-11-10T20:47:09
    verdict: str | None  # "good" | "weak" | "unusable", None if never rated
    screens: list[str]
    meta: dict = field(repr=False)

    @property
    def usable(self) -> bool:
        return self.verdict != "unusable"


@dataclass(frozen=True, slots=True)
class Choice:
    recording: RecordingInfo
    weak: bool  # only weak recordings exist for this condition
    skipped: list[RecordingInfo]  # newer recordings passed over (weak or unusable)


def read_recordings(data_dir: Path = CALIBRATION_DIR) -> list[RecordingInfo]:
    """All readable recordings, oldest first."""
    if not data_dir.exists():
        return []
    out = []
    for path in sorted(data_dir.iterdir()):
        try:
            meta = json.loads((path / "meta.json").read_text())
            out.append(
                RecordingInfo(
                    path=path,
                    condition=meta["condition"],
                    started=meta["started"],
                    verdict=(meta.get("quality") or {}).get("verdict"),
                    screens=[s["name"] for s in meta["screens"]],
                    meta=meta,
                )
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def choose(recordings: list[RecordingInfo], condition: str | None = None) -> Choice | None:
    """The recording to use for a condition (None: any), or None if nothing usable."""
    newest_first = [r for r in reversed(recordings) if condition in (None, r.condition)]
    skipped = []
    for r in newest_first:
        if r.verdict in ("good", None):
            return Choice(r, weak=False, skipped=skipped)
        skipped.append(r)
    weak = next((r for r in newest_first if r.verdict == "weak"), None)
    if weak is None:
        return None
    newer = [r for r in skipped if r.started > weak.started]
    return Choice(weak, weak=True, skipped=newer)


def pick_prior(
    recordings: list[RecordingInfo], screens: list[str], condition: str
) -> RecordingInfo | None:
    """For the wrong-screen check: newest good recording with these screens, same condition first.

    Unlike choose(), never falls back to weak or unrated recordings: their
    mistakes would look like the user's.
    """
    good = [r for r in reversed(recordings) if r.verdict == "good" and r.screens == screens]
    same = [r for r in good if r.condition == condition]
    return (same or good or [None])[0]
