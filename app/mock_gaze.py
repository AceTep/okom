"""Fake gaze source: the mouse position plays the role of the gaze point.

Sends the same UDP messages as the real gaze engine, with added Gaussian
noise and latency so that the decision logic is tested under realistic
conditions. Run alongside app.main:

    python -m app.mock_gaze
"""

from __future__ import annotations

import argparse
import logging
import random
import socket
import time
from collections import deque

from app.backends.base import Screen
from app.backends.detect import create_backend
from app.config import MockGazeConfig, load_config
from shared.protocol import GazeMessage

log = logging.getLogger("app.mock_gaze")


def locate(screens: list[Screen], px: float, py: float) -> tuple[int, float, float]:
    """Screen index and normalized point for a global pixel position.

    A point outside every screen is clamped to the nearest one, the way a
    gaze classifier always picks some screen.
    """

    def distance(s: Screen) -> float:
        r = s.rect
        dx = max(r.x - px, 0, px - (r.x + r.w - 1))
        dy = max(r.y - py, 0, py - (r.y + r.h - 1))
        return dx * dx + dy * dy

    screen = min(screens, key=distance)
    r = screen.rect
    x = min(max((px - r.x) / r.w, 0.0), 1.0)
    y = min(max((py - r.y) / r.h, 0.0), 1.0)
    return screen.index, x, y


def make_message(
    screens: list[Screen],
    cursor: tuple[int, int],
    t: float,
    cfg: MockGazeConfig,
    rng: random.Random,
) -> GazeMessage:
    sigma = cfg.noise_cm * cfg.px_per_cm
    px = cursor[0] + rng.gauss(0.0, sigma)
    py = cursor[1] + rng.gauss(0.0, sigma)
    index, x, y = locate(screens, px, py)
    return GazeMessage(t=t, face=True, users=1, screen=index, x=x, y=y, conf=cfg.conf, blink=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mouse-driven fake gaze source.")
    parser.add_argument("--seed", type=int, default=None, help="noise seed for repeatable runs")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    config = load_config()
    cfg = config.mock_gaze
    backend = create_backend()
    stream = backend.open_cursor_stream(interval_ms=round(1000 / cfg.rate_hz))
    if stream is None:
        raise SystemExit(
            f"mock_gaze needs the mouse position, backend '{backend.name}' cannot give it"
        )
    screens = backend.list_screens()
    for s in screens:
        log.info("screen %d = %s %s", s.index, s.name, s.rect)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (config.udp.host, config.udp.port)
    rng = random.Random(args.seed)
    pending: deque[tuple[float, GazeMessage]] = deque()  # (send at monotonic, msg)
    period = 1.0 / cfg.rate_hz
    log.info(
        "sending to udp://%s:%d at %.0f Hz, noise %.1f cm, delay %.0f ms",
        *target,
        cfg.rate_hz,
        cfg.noise_cm,
        cfg.delay_s * 1000,
    )
    next_tick = time.monotonic()
    try:
        while True:
            cursor = stream.latest()
            now = time.monotonic()
            if cursor is not None:
                msg = make_message(screens, cursor, time.time(), cfg, rng)
                pending.append((now + cfg.delay_s, msg))
            while pending and pending[0][0] <= now:
                sock.sendto(pending.popleft()[1].to_json().encode(), target)
            next_tick += period
            time.sleep(max(0.0, next_tick - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        stream.close()
        backend.close()
        sock.close()


if __name__ == "__main__":
    main()
