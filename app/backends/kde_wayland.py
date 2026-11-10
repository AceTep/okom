"""KDE Plasma 6 (KWin) backend, works on Wayland and X11 sessions.

Wayland gives clients no way to list or activate other windows, so we ask the
compositor itself: a short KWin script is loaded over D-Bus, it does the work
inside KWin and sends the result back with callDBus() to a method call on our
own D-Bus connection. No external tools are needed.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid

from jeepney import DBusAddress, MatchRule, MessageType, new_method_call, new_method_return
from jeepney.io.blocking import DBusConnection, open_dbus_connection

from app.backends.base import FocusBackend, Rect, Screen, Window, index_screens

log = logging.getLogger(__name__)

_SCRIPTING = DBusAddress("/Scripting", bus_name="org.kde.KWin", interface="org.kde.kwin.Scripting")
_REPLY_PATH = "/okom"
_REPLY_IFACE = "okom.Bridge"

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


class KdeWaylandBackend(FocusBackend):
    name = "kde_wayland"

    def __init__(self, timeout: float = 1.0) -> None:
        self._timeout = timeout
        self._conn: DBusConnection = open_dbus_connection(bus="SESSION")

    def close(self) -> None:
        self._conn.close()

    def list_screens(self) -> list[Screen]:
        return self.snapshot()[0]

    def list_windows(self) -> list[Window]:
        return self.snapshot()[1]

    def snapshot(self) -> tuple[list[Screen], list[Window]]:
        """Screens and windows from a single script run."""
        data = self._run(_LIST_JS, {})
        screens = index_screens([(s["name"], _rect(s)) for s in data["screens"]])
        windows = [
            Window(w["id"], w["title"], _rect(w), w["screen"], int(w["stack"]), bool(w["active"]))
            for w in data["windows"]
        ]
        return screens, windows

    def focus(self, window_id: str) -> bool:
        return bool(self._run(_FOCUS_JS, {"wid": json.dumps(window_id)})["ok"])

    def _run(self, template: str, params: dict[str, str]) -> dict:
        """Load a one-shot KWin script, run it and wait for its reply."""
        token = uuid.uuid4().hex
        plugin = f"okom_{token}"
        source = template % {
            "service": json.dumps(self._conn.unique_name),
            "path": json.dumps(_REPLY_PATH),
            "iface": json.dumps(_REPLY_IFACE),
            "token": json.dumps(token),
            **params,
        }
        fd, path = tempfile.mkstemp(prefix="okom_", suffix=".js")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(source)
            rule = MatchRule(type="method_call", interface=_REPLY_IFACE, member="reply")
            with self._conn.filter(rule) as queue:
                script_id = self._call(_SCRIPTING, "loadScript", "ss", (path, plugin))[0]
                if script_id < 0:
                    raise RuntimeError("KWin refused to load the script")
                try:
                    script = DBusAddress(
                        f"/Scripting/Script{script_id}",
                        bus_name="org.kde.KWin",
                        interface="org.kde.kwin.Script",
                    )
                    self._call(script, "run")
                    return self._await_reply(queue, token)
                finally:
                    self._call(_SCRIPTING, "unloadScript", "s", (plugin,))
        finally:
            os.unlink(path)

    def _await_reply(self, queue, token: str) -> dict:
        while True:
            msg = self._conn.recv_until_filtered(queue, timeout=self._timeout)
            self._conn.send(new_method_return(msg))
            got_token, payload = msg.body
            if got_token == token:
                return json.loads(payload)
            log.debug("ignoring stale KWin reply %s", got_token)

    def _call(self, addr: DBusAddress, method: str, sig: str | None = None, body: tuple = ()):
        reply = self._conn.send_and_get_reply(
            new_method_call(addr, method, sig, body), timeout=self._timeout
        )
        if reply.header.message_type == MessageType.error:
            raise RuntimeError(f"KWin {method} failed: {reply.body}")
        return reply.body


def _rect(d: dict) -> Rect:
    return Rect(int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"]))


if __name__ == "__main__":
    import argparse
    import time

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="List windows or focus one through KWin.")
    parser.add_argument("--focus", metavar="ID", help="window id to focus")
    args = parser.parse_args()

    backend = KdeWaylandBackend()
    if args.focus:
        log.info("focus %s -> %s", args.focus, backend.focus(args.focus))
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
