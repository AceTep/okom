"""Pick the focus backend for the current platform automatically."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Mapping

from app.backends.base import FocusBackend
from app.backends.dummy import DummyBackend

log = logging.getLogger(__name__)

HINTS = {
    "windows": "Install pywin32: uv pip install pywin32",
    "kde_wayland": "Check that KWin scripting is reachable: "
    "busctl --user introspect org.kde.KWin /Scripting",
}


def choose_backend(platform: str, env: Mapping[str, str]) -> str:
    """Return the backend name for a platform and environment. Pure function."""
    desktop = env.get("XDG_CURRENT_DESKTOP", "").upper()
    if platform == "win32":
        return "windows"
    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if env.get("SWAYSOCK"):
        return "sway"
    session = env.get("XDG_SESSION_TYPE", "").lower()
    if session == "x11" or (not session and env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY")):
        return "x11"
    if "KDE" in desktop:
        return "kde_wayland"
    if "GNOME" in desktop:
        return "gnome_wayland"
    return "dummy"


def _factories() -> dict[str, Callable[[], FocusBackend]]:
    def kde() -> FocusBackend:
        from app.backends.kde_wayland import KdeWaylandBackend

        return KdeWaylandBackend()

    return {"kde_wayland": kde}


def create_backend(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    factories: Mapping[str, Callable[[], FocusBackend]] | None = None,
) -> FocusBackend:
    """Create and verify a backend; fall back to dummy with a clear reason."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    factories = _factories() if factories is None else factories

    name = choose_backend(platform, env)
    log.info("detected platform backend: %s", name)
    if name == "dummy":
        return _fallback("no supported desktop detected (XDG_CURRENT_DESKTOP, session type)")
    factory = factories.get(name)
    if factory is None:
        return _fallback(f"backend '{name}' is not implemented yet")

    try:
        backend = factory()
        windows = backend.list_windows()
    except Exception as exc:  # noqa: BLE001 - any failure means fall back
        return _fallback(f"backend '{name}' failed to start: {exc}. {HINTS.get(name, '')}")
    if not windows:
        backend.close()
        return _fallback(f"backend '{name}' sees no windows. {HINTS.get(name, '')}")
    log.info("backend %s sees %d windows", name, len(windows))
    return backend


def _fallback(reason: str) -> DummyBackend:
    log.warning("focus switching disabled, using dummy backend: %s", reason)
    return DummyBackend(reason)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    create_backend().close()
