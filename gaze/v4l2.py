"""Minimal Linux V4L2 control access (read and write camera controls).

OpenCV does not expose every UVC control, so the few we need are set with
ioctl directly. Linux only; callers check sys.platform first.
"""

from __future__ import annotations

import fcntl
import logging
import os
import struct

log = logging.getLogger(__name__)

# linux/videodev2.h
EXPOSURE_DYNAMIC_FRAMERATE = 0x009A0903  # V4L2_CID_EXPOSURE_AUTO_PRIORITY

_CTRL = struct.Struct("Ii")  # struct v4l2_control { __u32 id; __s32 value; }


def _iowr(nr: int, size: int) -> int:
    return (3 << 30) | (size << 16) | (ord("V") << 8) | nr


_G_CTRL = _iowr(27, _CTRL.size)
_S_CTRL = _iowr(28, _CTRL.size)


def get_control(device: str, cid: int) -> int:
    fd = os.open(device, os.O_RDWR)
    try:
        buf = bytearray(_CTRL.pack(cid, 0))
        fcntl.ioctl(fd, _G_CTRL, buf)
        return _CTRL.unpack(buf)[1]
    finally:
        os.close(fd)


def set_control(device: str, cid: int, value: int) -> None:
    fd = os.open(device, os.O_RDWR)
    try:
        fcntl.ioctl(fd, _S_CTRL, bytearray(_CTRL.pack(cid, value)))
    finally:
        os.close(fd)


class ControlOverride:
    """Set a control and remember the old value so it can be restored."""

    def __init__(self, device: str, cid: int, value: int) -> None:
        self.device = device
        self.cid = cid
        self.original = get_control(device, cid)
        set_control(device, cid, value)

    def restore(self) -> None:
        try:
            set_control(self.device, self.cid, self.original)
        except OSError as exc:
            log.warning("could not restore control %#x on %s: %s", self.cid, self.device, exc)
