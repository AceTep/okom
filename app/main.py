"""Application: receive gaze, decide, move keyboard focus.

python -m app.main
"""

from __future__ import annotations

import logging
import time

from app.backends.base import FocusBackend
from app.backends.detect import create_backend
from app.config import load_config
from app.decision import ScreenDecider
from app.mapping import focus_target, screen_of_active
from app.receiver import GazeReceiver
from shared.protocol import GazeMessage

log = logging.getLogger("app.main")

_IDLE_TIMEOUT_S = 1.0  # no message for this long counts as "gaze stream stopped"


def switch_to(backend: FocusBackend, screen_index: int, msg: GazeMessage) -> None:
    screens, windows = backend.snapshot()
    target = focus_target(screens, windows, screen_index)
    latency_ms = (time.time() - msg.t) * 1000
    if target is None:
        log.info("screen %d: already focused or no windows, nothing to do", screen_index)
        return
    ok = backend.focus(target.id)
    log.info(
        "screen %d: focus %r [%s] -> %s (%.0f ms after the deciding sample)",
        screen_index,
        target.title,
        target.screen,
        "ok" if ok else "FAILED",
        latency_ms,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = load_config()
    backend = create_backend()
    receiver = GazeReceiver(config.udp.host, config.udp.port)

    screens, windows = backend.snapshot()
    decider = ScreenDecider(config.decision, current=screen_of_active(screens, windows))
    log.info("focused screen at start: %s", decider.current)

    receiving = False
    try:
        while True:
            msg = receiver.recv(timeout=_IDLE_TIMEOUT_S)
            if msg is None:
                if receiving:
                    log.info("gaze stream stopped")
                    receiving = False
                continue
            if not receiving:
                log.info("gaze stream started")
                receiving = True
            screen = decider.update(msg)
            if screen is None:
                continue
            try:
                switch_to(backend, screen, msg)
            except Exception:  # keep running if one backend call fails
                log.exception("focus switch to screen %d failed", screen)
    except KeyboardInterrupt:
        pass
    finally:
        receiver.close()
        backend.close()


if __name__ == "__main__":
    main()
