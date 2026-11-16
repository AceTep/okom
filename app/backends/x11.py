"""X11 backend: EWMH for listing windows, plus a focus method that suits the window manager.

Windows and screens come from standard properties (python-xlib), so this works with
any EWMH window manager. Giving focus is where window managers differ:

- `ewmh`: send `_NET_ACTIVE_WINDOW` to the root window. Most window managers focus
  the window. Vanilla dwm does not: it only marks the window urgent.
- `pointer`: warp the mouse pointer into the window. dwm (and other focus-follows-mouse
  managers) focus whatever is under the pointer and select its monitor. Tiled windows
  do not overlap, so the target is unambiguous. The pointer visibly jumps.

`focus_method: auto` picks `pointer` for dwm and `ewmh` for everything else.
"""

from __future__ import annotations

import logging
import time

from Xlib import X, Xatom, display, error
from Xlib.protocol import event

from app.backends.base import (
    CursorStream,
    FocusBackend,
    FocusEvents,
    Rect,
    Screen,
    Window,
    index_screens,
)

log = logging.getLogger(__name__)

FOCUS_METHODS = ("auto", "pointer", "ewmh")
_POINTER_WMS = frozenset({"dwm"})
_FOCUS_WAIT_S = 0.3  # how long to wait for the window manager to report the new active window
_SKIP_STATES = ("_NET_WM_STATE_HIDDEN", "_NET_WM_STATE_SKIP_TASKBAR")


# --- pure helpers (no X server needed, covered by tests/test_x11.py) -------------------


def resolve_focus_method(configured: str, wm_name: str) -> str:
    """`pointer` or `ewmh` for a configured value and the window manager's name."""
    if configured not in FOCUS_METHODS:
        raise ValueError(f"x11.focus_method must be one of {FOCUS_METHODS}, got {configured!r}")
    if configured != "auto":
        return configured
    return "pointer" if wm_name.lower() in _POINTER_WMS else "ewmh"


def assign_screen(rect: Rect, screens: list[Screen]) -> str | None:
    """Name of the screen the window mostly covers, or None if it is on none of them.

    dwm hides windows of other tags by moving them off-screen, so zero overlap means
    "not visible on the current desktop".
    """
    best = max(screens, key=lambda s: s.rect.area_overlap(rect), default=None)
    if best is None or best.rect.area_overlap(rect) == 0:
        return None
    return best.name


def focus_point(rect: Rect) -> tuple[int, int]:
    """Where to put the pointer so it is inside the window."""
    return rect.x + rect.w // 2, rect.y + rect.h // 2


# --- backend ---------------------------------------------------------------------------


class X11Backend(FocusBackend):
    name = "x11"

    def __init__(self, focus_method: str = "auto") -> None:
        if focus_method not in FOCUS_METHODS:
            raise ValueError(
                f"x11.focus_method must be one of {FOCUS_METHODS}, got {focus_method!r}"
            )
        self._d = display.Display()  # raises DisplayError when there is no X server
        self._root = self._d.screen().root
        self._atom_cache: dict[str, int] = {}
        self.wm_name = self._read_wm_name()
        self.focus_method = resolve_focus_method(focus_method, self.wm_name)
        log.info(
            "x11: window manager %r, focus method %s", self.wm_name or "unknown", self.focus_method
        )

    # -- X helpers --

    def _atom(self, name: str) -> int:
        if name not in self._atom_cache:
            self._atom_cache[name] = self._d.intern_atom(name)
        return self._atom_cache[name]

    def _prop(self, win, name: str, prop_type: int = X.AnyPropertyType):  # noqa: ANN001
        """Property value (a sequence) or None."""
        reply = win.get_full_property(self._atom(name), prop_type)
        return None if reply is None else reply.value

    def _read_wm_name(self) -> str:
        try:
            check = self._prop(self._root, "_NET_SUPPORTING_WM_CHECK", Xatom.WINDOW)
            if not check:
                return ""
            wm_win = self._d.create_resource_object("window", int(check[0]))
            return self._title(wm_win)
        except error.XError:
            return ""

    def _title(self, win) -> str:  # noqa: ANN001
        raw = self._prop(win, "_NET_WM_NAME", self._atom("UTF8_STRING"))
        if raw:
            return bytes(raw).decode("utf-8", "replace")
        name = win.get_wm_name()
        if isinstance(name, bytes):
            return name.decode("latin-1", "replace")
        return name or ""

    def _active_id(self) -> int | None:
        value = self._prop(self._root, "_NET_ACTIVE_WINDOW", Xatom.WINDOW)
        return int(value[0]) if value and int(value[0]) else None

    def _is_normal(self, win) -> bool:  # noqa: ANN001
        types = self._prop(win, "_NET_WM_WINDOW_TYPE", Xatom.ATOM)
        if types and self._atom("_NET_WM_WINDOW_TYPE_NORMAL") not in [int(t) for t in types]:
            return False
        states = self._prop(win, "_NET_WM_STATE", Xatom.ATOM)
        skip = {self._atom(s) for s in _SKIP_STATES}
        return not (states and skip & {int(s) for s in states})

    def _rect(self, win) -> Rect:  # noqa: ANN001
        geometry = win.get_geometry()
        pos = self._root.translate_coords(win, 0, 0)  # window origin in root coordinates
        return Rect(pos.x, pos.y, geometry.width, geometry.height)

    # -- FocusBackend --

    def list_screens(self) -> list[Screen]:
        try:
            monitors = self._root.xrandr_get_monitors().monitors
            named = [
                (
                    self._d.get_atom_name(m.name),
                    Rect(m.x, m.y, m.width_in_pixels, m.height_in_pixels),
                )
                for m in monitors
            ]
        except (error.XError, AttributeError):  # no RandR 1.5: treat the desktop as one screen
            named = []
        if not named:
            geometry = self._root.get_geometry()
            named = [("x11", Rect(0, 0, geometry.width, geometry.height))]
        return index_screens(named)

    def list_windows(self) -> list[Window]:
        return self.snapshot()[1]

    def snapshot(self) -> tuple[list[Screen], list[Window]]:
        screens = self.list_screens()
        clients = self._prop(self._root, "_NET_CLIENT_LIST", Xatom.WINDOW) or []
        stacking = self._prop(self._root, "_NET_CLIENT_LIST_STACKING", Xatom.WINDOW) or clients
        order = {int(w): i for i, w in enumerate(stacking)}
        active = self._active_id()
        windows: list[Window] = []
        for wid in dict.fromkeys(int(w) for w in clients):  # dwm can list a client twice
            win = self._d.create_resource_object("window", wid)
            try:
                if win.get_attributes().map_state != X.IsViewable or not self._is_normal(win):
                    continue
                rect = self._rect(win)
                screen = assign_screen(rect, screens)
                if screen is None:
                    continue  # on another tag or off-screen
                title = self._title(win)
            except error.XError:  # the window closed while we were looking at it
                continue
            windows.append(Window(str(wid), title, rect, screen, order.get(wid, 0), wid == active))
        return screens, windows

    def focus(self, window_id: str) -> bool:
        wid = int(window_id)
        win = self._d.create_resource_object("window", wid)
        try:
            if self.focus_method == "pointer":
                x, y = focus_point(self._rect(win))
                self._root.warp_pointer(x, y)
            else:
                msg = event.ClientMessage(
                    window=win,
                    client_type=self._atom("_NET_ACTIVE_WINDOW"),
                    data=(32, [1, X.CurrentTime, 0, 0, 0]),  # 1 = request comes from a pager
                )
                mask = X.SubstructureRedirectMask | X.SubstructureNotifyMask
                self._root.send_event(msg, event_mask=mask)
            self._d.sync()
        except error.XError as exc:
            log.warning("x11: focus %s failed: %s", window_id, exc)
            return False
        return self._wait_active(wid)

    def _wait_active(self, wid: int) -> bool:
        deadline = time.monotonic() + _FOCUS_WAIT_S
        while True:
            if self._active_id() == wid:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def open_focus_events(self) -> FocusEvents | None:
        return _X11FocusEvents(self)

    def open_cursor_stream(self, interval_ms: int = 33) -> CursorStream | None:
        return _X11Cursor(self._root)

    def screen_name_of(self, wid: int) -> str | None:
        """Screen a window is on right now, or None."""
        try:
            win = self._d.create_resource_object("window", wid)
            return assign_screen(self._rect(win), self.list_screens())
        except error.XError:
            return None

    def close(self) -> None:
        self._d.close()


class _X11FocusEvents(FocusEvents):
    """Active-window changes from PropertyNotify on the root window.

    Uses its own connection, so reading events never mixes with the backend's requests.
    """

    def __init__(self, backend: X11Backend) -> None:
        self._backend = backend
        self._d = display.Display()
        root = self._d.screen().root
        root.change_attributes(event_mask=X.PropertyChangeMask)
        self._atom = self._d.intern_atom("_NET_ACTIVE_WINDOW")
        self._d.sync()

    def poll(self) -> str | None:
        changed = False
        while self._d.pending_events():
            ev = self._d.next_event()
            if ev.type == X.PropertyNotify and ev.atom == self._atom:
                changed = True
        if not changed:
            return None
        active = self._backend._active_id()  # noqa: SLF001 - same package, same display
        return None if active is None else self._backend.screen_name_of(active)

    def close(self) -> None:
        self._d.close()


class _X11Cursor(CursorStream):
    """Pointer position; one cheap request per call, so there is no thread to stop."""

    def __init__(self, root) -> None:  # noqa: ANN001
        self._root = root

    def latest(self) -> tuple[int, int] | None:
        try:
            pointer = self._root.query_pointer()
        except error.XError:
            return None
        return pointer.root_x, pointer.root_y

    def close(self) -> None:
        pass


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Inspect the X11 backend.")
    parser.add_argument("--focus", metavar="ID", help="window id to focus")
    parser.add_argument("--method", choices=FOCUS_METHODS, default="auto")
    args = parser.parse_args()

    backend = X11Backend(args.method)
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
