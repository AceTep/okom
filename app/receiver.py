"""Receive gaze messages over UDP."""

from __future__ import annotations

import logging
import socket
import time

from shared.protocol import GazeMessage, ProtocolError

log = logging.getLogger(__name__)

_MAX_DATAGRAM = 4096
_WARN_EVERY_S = 5.0


class GazeReceiver:
    def __init__(self, host: str, port: int) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.bind((host, port))
        except OSError as exc:
            self._sock.close()
            raise OSError(f"cannot listen on {host}:{port} (already running?): {exc}") from exc
        self.invalid = 0
        self._unreported = 0
        self._last_warn = 0.0
        log.info("listening for gaze on udp://%s:%d", host, port)

    def recv(self, timeout: float) -> GazeMessage | None:
        """Next valid message, or None if nothing valid arrived within timeout."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._sock.settimeout(remaining)
            try:
                data = self._sock.recv(_MAX_DATAGRAM)
            except TimeoutError:
                return None
            try:
                return GazeMessage.from_json(data)
            except ProtocolError as exc:
                self._invalid(exc)

    def close(self) -> None:
        self._sock.close()

    def _invalid(self, exc: ProtocolError) -> None:
        """Count bad messages and warn at most every few seconds."""
        self.invalid += 1
        self._unreported += 1
        now = time.monotonic()
        if now - self._last_warn >= _WARN_EVERY_S:
            log.warning("dropped %d invalid message(s), last: %s", self._unreported, exc)
            self._unreported = 0
            self._last_warn = now
