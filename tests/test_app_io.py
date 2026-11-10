"""Config loading, mock gaze geometry and the UDP receiver (localhost only)."""

import random
import socket

import pytest

from app.backends.base import Rect, Screen
from app.config import DEFAULT_PATH, load_config
from app.mock_gaze import locate, make_message
from app.receiver import GazeReceiver
from shared.protocol import GazeMessage

SCREENS = [
    Screen(0, "HDMI-A-1", Rect(0, 0, 1920, 1080)),
    Screen(1, "eDP-1", Rect(0, 1080, 1920, 1080)),
]


def test_default_config_loads() -> None:
    cfg = load_config(DEFAULT_PATH)
    assert cfg.udp.port == 5555
    assert cfg.decision.dwell_s == pytest.approx(0.4)


def test_config_rejects_unknown_key(tmp_path) -> None:
    text = DEFAULT_PATH.read_text().replace("dwell_s:", "dwel_s:")
    path = tmp_path / "c.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="dwel_s"):
        load_config(path)


def test_locate_inside_and_outside() -> None:
    assert locate(SCREENS, 960, 540) == (0, 0.5, 0.5)
    index, x, y = locate(SCREENS, 960, 1080 + 540)
    assert index == 1 and y == pytest.approx(0.5)
    assert locate(SCREENS, 960, 5000)[0] == 1  # below everything -> nearest (laptop)
    assert locate(SCREENS, -50, 100) == (0, 0.0, pytest.approx(100 / 1080))


def test_mock_message_is_valid_and_noisy() -> None:
    cfg = load_config().mock_gaze
    rng = random.Random(1)
    msgs = [make_message(SCREENS, (960, 540), 1.0, cfg, rng) for _ in range(200)]
    assert all(m.screen == 0 for m in msgs)  # 540 px from the edge is > 3 sigma (160 px)
    assert len({m.x for m in msgs}) > 100


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_receiver_skips_invalid_messages() -> None:
    port = free_port()
    rx = GazeReceiver("127.0.0.1", port)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        good = GazeMessage(t=1.0, face=True, users=1, screen=0, x=0.1, y=0.2, conf=0.9, blink=False)
        tx.sendto(b"garbage", ("127.0.0.1", port))
        tx.sendto(good.to_json().encode(), ("127.0.0.1", port))
        assert rx.recv(timeout=1.0) == good
        assert rx.invalid == 1
        assert rx.recv(timeout=0.05) is None
    finally:
        tx.close()
        rx.close()
