"""KDE Plasma 6 (KWin) backend, works on Wayland and X11 sessions.

Wayland gives clients no way to list or activate other windows, so we ask the
compositor itself: a short KWin script is loaded over D-Bus, it does the work
inside KWin and sends the result back with callDBus() to a method call on our
own D-Bus connection. No external tools are needed.

Two kinds of scripts are used:
- one-shot scripts (list windows, focus a window): loaded, run, unloaded;
- one persistent cursor script for app.mock_gaze, because loading a script
  30 times per second costs KWin about 15 % of a CPU core (measured).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from collections import deque

from jeepney import (
    DBusAddress,
    MatchRule,
    Message,
    MessageType,
    new_method_call,
    new_method_return,
)
from jeepney.io.blocking import DBusConnection, open_dbus_connection
from jeepney.low_level import MessageFlag

from app.backends.base import CursorStream, FocusBackend, Rect, Screen, Window, index_screens

log = logging.getLogger(__name__)

_SCRIPTING = DBusAddress("/Scripting", bus_name="org.kde.KWin", interface="org.kde.kwin.Scripting")
_EFFECTS = DBusAddress("/Effects", bus_name="org.kde.KWin", interface="org.kde.kwin.Effects")
# Built-in KWin effect that dims every window except the active one. Loaded at
# runtime only (not saved in the user's settings), so unloading restores the desktop.
_HIGHLIGHT_EFFECT = "diminactive"
_REPLY_PATH = "/okom"
_REPLY_IFACE = "okom.Bridge"
_CURSOR_PLUGIN = "okom_cursor"

# Runs inside KWin. Placeholders are filled with json.dumps() values.
_LIST_JS = """
const desk = workspace.currentDesktop;
const active = workspace.activeWindow;
const wins = [];
const stack = workspace.stackingOrder;
for (let i = 0; i < stack.length; i++) {
    const w = stack[i];
    if (!w.normalWindow || w.minimized || w.skipTaskbar || w.deleted) continue;
    if (!w.onAllDesktops && !w.desktops.some(d => d.id === desk.id)) continue;
    const g = w.frameGeometry;
    wins.push({id: w.internalId.toString(), title: w.caption, x: g.x, y: g.y,
               w: g.width, h: g.height, screen: w.output ? w.output.name : "",
               stack: i, active: w === active});
}
const screens = workspace.screens.map(s => ({name: s.name, x: s.geometry.x,
    y: s.geometry.y, w: s.geometry.width, h: s.geometry.height}));
callDBus(%(service)s, %(path)s, %(iface)s, "reply", %(token)s,
         JSON.stringify({windows: wins, screens: screens}));
"""

_FOCUS_JS = """
let ok = false;
for (const w of workspace.stackingOrder) {
    if (w.internalId.toString() === %(wid)s) {
        if (w.minimized) w.minimized = false;
        workspace.activeWindow = w;
        ok = workspace.activeWindow === w;
        break;
    }
}
callDBus(%(service)s, %(path)s, %(iface)s, "reply", %(token)s, JSON.stringify({ok: ok}));
"""

# Persistent: reports the cursor position at most every `interval` ms, and
# only when it has moved, so an idle mouse costs nothing.
_CURSOR_JS = """
let lastX = null, lastY = null;
const timer = new QTimer();
timer.interval = %(interval)s;
timer.timeout.connect(() => {
    const p = workspace.cursorPos;
    if (p.x === lastX && p.y === lastY) return;
    lastX = p.x;
    lastY = p.y;
    callDBus(%(service)s, %(path)s, %(iface)s, "cursor", p.x, p.y);
});
timer.start();
"""


class KdeWaylandBackend(FocusBackend):
    name = "kde_wayland"

    def __init__(self, timeout: float = 1.0) -> None:
        self._timeout = timeout
        self._conn: DBusConnection = open_dbus_connection(bus="SESSION")
        self._loaded_highlight = False

    def close(self) -> None:
        self.stop_highlight()
        self._conn.close()

    def start_highlight(self) -> bool:
        """Turn on KWin's "Dim Inactive" effect unless the user already has it on."""
        try:
            if self._effect("isEffectLoaded")[0]:
                log.info("highlight: %s already on, leaving it as it is", _HIGHLIGHT_EFFECT)
                return True
            ok = self._effect("loadEffect")[0]
        except (RuntimeError, TimeoutError) as exc:
            log.warning("highlight: cannot load %s: %s", _HIGHLIGHT_EFFECT, exc)
            return False
        self._loaded_highlight = bool(ok)
        log.info("highlight: %s %s", _HIGHLIGHT_EFFECT, "on" if ok else "could not be loaded")
        return bool(ok)

    def stop_highlight(self) -> None:
        """Turn the effect off again, but only if start_highlight() turned it on."""
        if not self._loaded_highlight:
            return
        self._loaded_highlight = False
        try:
            self._effect("unloadEffect")
            log.info("highlight: %s off", _HIGHLIGHT_EFFECT)
        except (RuntimeError, TimeoutError) as exc:
            log.warning("highlight: cannot unload %s: %s", _HIGHLIGHT_EFFECT, exc)

    def _effect(self, method: str) -> tuple:
        return _call(self._conn, _EFFECTS, method, "s", (_HIGHLIGHT_EFFECT,), self._timeout)

    def list_screens(self) -> list[Screen]:
        return self.snapshot()[0]

    def list_windows(self) -> list[Window]:
        return self.snapshot()[1]

    def snapshot(self) -> tuple[list[Screen], list[Window]]:
        data = self._run(_LIST_JS, {})
        screens = index_screens([(s["name"], _rect(s)) for s in data["screens"]])
        windows = [
            Window(w["id"], w["title"], _rect(w), w["screen"], int(w["stack"]), bool(w["active"]))
            for w in data["windows"]
        ]
        return screens, windows

    def focus(self, window_id: str) -> bool:
        return bool(self._run(_FOCUS_JS, {"wid": json.dumps(window_id)})["ok"])

    def open_cursor_stream(self, interval_ms: int = 33) -> CursorStream:
        return KdeCursorStream(interval_ms, self._timeout)

    def _run(self, template: str, params: dict[str, str]) -> dict:
        """Load a one-shot KWin script, run it and wait for its reply."""
        token = uuid.uuid4().hex
        plugin = f"okom_{token}"
        source = _fill(template, self._conn, token=json.dumps(token), **params)
        rule = MatchRule(type="method_call", interface=_REPLY_IFACE, member="reply")
        with _script_file(source) as path, self._conn.filter(rule) as queue:
            _load_and_run(self._conn, path, plugin, self._timeout)
            try:
                return self._await_reply(queue, token)
            finally:
                _call(self._conn, _SCRIPTING, "unloadScript", "s", (plugin,), self._timeout)

    def _await_reply(self, queue: deque, token: str) -> dict:
        while True:
            msg = self._conn.recv_until_filtered(queue, timeout=self._timeout)
            _ack(self._conn, msg)
            got_token, payload = msg.body
            if got_token == token:
                return json.loads(payload)
            log.debug("ignoring stale KWin reply %s", got_token)


class KdeCursorStream(CursorStream):
    """Cursor position pushed by a persistent KWin script.

    Uses its own D-Bus connection so cursor messages never mix with replies
    to one-shot scripts. A script left behind by a crashed run has a fixed
    plugin name and is unloaded on the next start.
    """

    def __init__(self, interval_ms: int, timeout: float) -> None:
        self._timeout = timeout
        self._conn = open_dbus_connection(bus="SESSION")
        self._queue: deque[Message] = deque()
        rule = MatchRule(type="method_call", interface=_REPLY_IFACE, member="cursor")
        self._filter = self._conn.filter(rule, queue=self._queue)
        self._latest: tuple[int, int] | None = None
        self._unload()  # leftover from a crashed run, if any
        source = _fill(_CURSOR_JS, self._conn, interval=str(int(interval_ms)))
        # KWin reads the file during loadScript, so it can be removed right after.
        with _script_file(source) as path:
            _load_and_run(self._conn, path, _CURSOR_PLUGIN, timeout)
        log.info("cursor stream started (every %d ms while the mouse moves)", interval_ms)

    def latest(self) -> tuple[int, int] | None:
        while True:
            try:
                self._conn.recv_messages(timeout=0)
            except TimeoutError:
                break
        while self._queue:
            msg = self._queue.popleft()
            _ack(self._conn, msg)
            x, y = msg.body
            self._latest = (int(x), int(y))
        return self._latest

    def close(self) -> None:
        try:
            self._unload()
        finally:
            self._filter.close()
            self._conn.close()

    def _unload(self) -> None:
        _call(self._conn, _SCRIPTING, "unloadScript", "s", (_CURSOR_PLUGIN,), self._timeout)


def _fill(template: str, conn: DBusConnection, **params: str) -> str:
    return template % {
        "service": json.dumps(conn.unique_name),
        "path": json.dumps(_REPLY_PATH),
        "iface": json.dumps(_REPLY_IFACE),
        **params,
    }


class _script_file:  # noqa: N801 - used as a context manager
    """Temporary .js file that is always removed."""

    def __init__(self, source: str) -> None:
        self._source = source
        self._path = ""

    def __enter__(self) -> str:
        fd, self._path = tempfile.mkstemp(prefix="okom_", suffix=".js")
        with os.fdopen(fd, "w") as f:
            f.write(self._source)
        return self._path

    def __exit__(self, *exc: object) -> None:
        os.unlink(self._path)


def _load_and_run(conn: DBusConnection, path: str, plugin: str, timeout: float) -> None:
    script_id = _call(conn, _SCRIPTING, "loadScript", "ss", (path, plugin), timeout)[0]
    if script_id < 0:
        raise RuntimeError(f"KWin refused to load script {plugin}")
    script = DBusAddress(
        f"/Scripting/Script{script_id}", bus_name="org.kde.KWin", interface="org.kde.kwin.Script"
    )
    _call(conn, script, "run", None, (), timeout)


def _call(
    conn: DBusConnection,
    addr: DBusAddress,
    method: str,
    sig: str | None,
    body: tuple,
    timeout: float,
) -> tuple:
    reply = conn.send_and_get_reply(new_method_call(addr, method, sig, body), timeout=timeout)
    if reply.header.message_type == MessageType.error:
        raise RuntimeError(f"KWin {method} failed: {reply.body}")
    return reply.body


def _ack(conn: DBusConnection, msg: Message) -> None:
    """Answer a method call from KWin so it does not wait for a reply."""
    if not msg.header.flags & MessageFlag.no_reply_expected:
        conn.send(new_method_return(msg))


def _rect(d: dict) -> Rect:
    return Rect(int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"]))


if __name__ == "__main__":
    import argparse
    import time

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Inspect the KWin backend.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--focus", metavar="ID", help="window id to focus")
    group.add_argument("--cursor", type=float, metavar="SEC", help="print cursor for SEC seconds")
    args = parser.parse_args()

    backend = KdeWaylandBackend()
    if args.focus:
        log.info("focus %s -> %s", args.focus, backend.focus(args.focus))
    elif args.cursor:
        stream = backend.open_cursor_stream()
        try:
            end = time.monotonic() + args.cursor
            while time.monotonic() < end:
                log.info("cursor %s", stream.latest())
                time.sleep(0.2)
        finally:
            stream.close()
    else:
        t0 = time.perf_counter()
        screens, windows = backend.snapshot()
        log.info("snapshot took %.1f ms", (time.perf_counter() - t0) * 1000)
        for s in screens:
            log.info("screen %d %s %s", s.index, s.name, s.rect)
        for w in sorted(windows, key=lambda w: -w.stack):
            mark = "*" if w.active else " "
            log.info("%s %s [%s] stack=%d %s", mark, w.id, w.screen, w.stack, w.title[:50])
    backend.close()
