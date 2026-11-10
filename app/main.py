"""Application: receive gaze, decide, move keyboard focus.

python -m app.main
"""

from __future__ import annotations

import logging
import time

from app.backends.base import FocusBackend, FocusEvents
from app.backends.detect import create_backend
from app.config import load_config
from app.decision import ScreenDecider
from app.mapping import focus_candidates, screen_of_active
from app.receiver import GazeReceiver
from shared.protocol import GazeMessage
from shared.signals import sigterm_as_keyboard_interrupt

log = logging.getLogger("app.main")

_IDLE_TIMEOUT_S = 1.0  # no message for this long counts as "gaze stream stopped"
_MAX_FOCUS_TRIES = 3  # windows tried on the target screen before giving up


def switch_to(backend: FocusBackend, screen_index: int, msg: GazeMessage) -> bool:
    """Focus the topmost window on the screen; fall back to the next ones if refused."""
    screens, windows = backend.snapshot()
    candidates = focus_candidates(screens, windows, screen_index)
    if not candidates:
        log.info("screen %d: already focused or no windows, nothing to do", screen_index)
        return True
    for attempt, target in enumerate(candidates[:_MAX_FOCUS_TRIES], start=1):
        if backend.focus(target.id):
            log.info(
                "screen %d: focus %r [%s] -> ok (%.0f ms after the deciding sample%s)",
                screen_index, target.title, target.screen, (time.time() - msg.t) * 1000,
                f", attempt {attempt}" if attempt > 1 else "",
            )  # fmt: skip
            return True
        log.warning(
            "screen %d: %r refused focus, trying the next window", screen_index, target.title
        )
    log.error("screen %d: no window accepted focus", screen_index)
    return False


def follow_focus(events: FocusEvents, screen_index: dict[str, int], decider: ScreenDecider) -> None:
    """Keep the decider in sync when focus moves by click, Alt+Tab or our own switch."""
    name = events.poll()
    if name is None:
        return
    screen = screen_index.get(name)
    if screen is None:
        log.warning("focus moved to unknown output %r (screens changed?)", name)
        return
    if decider.set_current(screen):
        log.info("focus moved to screen %d outside OKOM", screen)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = load_config()
    receiver = GazeReceiver(config.udp.host, config.udp.port)  # fails fast if the port is taken
    backend = create_backend()
    # A plain `kill` should also restore the desktop (e.g. turn the dimming off again).
    sigterm_as_keyboard_interrupt()
    events = None
    try:
        if config.highlight.dim_inactive and not backend.start_highlight():
            log.info("highlight is not available with the %s backend", backend.name)
        screens, windows = backend.snapshot()
        screen_index = {s.name: s.index for s in screens}
        decider = ScreenDecider(config.decision, current=screen_of_active(screens, windows))
        log.info("focused screen at start: %s", decider.current)
        events = backend.open_focus_events()
        if events is None:
            log.info("%s backend cannot report focus changes made outside OKOM", backend.name)
        receiving = False
        while True:
            if events is not None:
                follow_focus(events, screen_index, decider)
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
        if events is not None:
            events.close()
        backend.stop_highlight()
        backend.close()
        receiver.close()


if __name__ == "__main__":
    main()
