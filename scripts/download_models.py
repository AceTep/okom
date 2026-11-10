"""Download the MediaPipe model files into models/ and verify their checksums.

python scripts/download_models.py
"""

from __future__ import annotations

import hashlib
import logging
import sys
import urllib.request
from pathlib import Path

log = logging.getLogger("download_models")

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

# (file name, URL with a pinned model version, sha256)
MODELS = [
    (
        "face_landmarker.task",
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task",
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    ),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name: str, url: str, digest: str) -> None:
    dest = MODELS_DIR / name
    if dest.exists() and sha256(dest) == digest:
        log.info("%s: already present", name)
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("%s: downloading %s", name, url)
    with urllib.request.urlopen(url, timeout=60) as response, tmp.open("wb") as f:
        while chunk := response.read(1 << 20):
            f.write(chunk)
    got = sha256(tmp)
    if got != digest:
        tmp.unlink()
        raise RuntimeError(f"{name}: checksum mismatch (got {got}, expected {digest})")
    tmp.replace(dest)
    log.info("%s: ok (%d bytes)", name, dest.stat().st_size)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    MODELS_DIR.mkdir(exist_ok=True)
    try:
        for model in MODELS:
            fetch(*model)
    except Exception as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
