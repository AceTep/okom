"""Send gaze messages to app/ over UDP."""

from __future__ import annotations

import logging
import socket

from shared.protocol import GazeMessage

log = logging.getLogger(__name__)


class GazeSender:
    def __init__(self, host: str, port: int) -> None:
        self._target = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sent = 0
        self.failed = 0

    def send(self, msg: GazeMessage) -> None:
        try:
            self._sock.sendto(msg.to_json().encode(), self._target)
            self.sent += 1
        except OSError as exc:  # e.g. network unreachable; never stop the engine for it
            self.failed += 1
            if self.failed == 1:
                log.warning("cannot send to udp://%s:%d: %s", *self._target, exc)

    def close(self) -> None:
        self._sock.close()
