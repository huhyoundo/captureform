"""Find windows and controls under the cursor for click-to-capture.

Qt6 makes the process per-monitor DPI aware, so every Win32 rect here is in
physical pixels. Qt keeps each screen's top-left in physical pixels and scales
only its size, so physical p on screen s maps to logical
s.topLeft + (p - s.topLeft) / dpr. The helpers below do that per screen.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QGuiApplication

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi")
    _user32.ChildWindowFromPointEx.restype = wintypes.HWND
    _user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_DWMWA_CLOAKED = 14
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_LWA_ALPHA = 0x2
_CWP_FLAGS = 0x0001 | 0x0004  # skip invisible, skip transparent
_MIN_SIZE = 12


@dataclass
class WindowInfo:
    hwnd: int
    rect: QRect  # physical pixels
    class_name: str


def _rect_from_win(rc: wintypes.RECT) -> QRect:
    return QRect(rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(128)
    _user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def _window_rect(hwnd: int, top_level: bool) -> QRect:
    rc = wintypes.RECT()
    if top_level:
        hr = _dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rc), ctypes.sizeof(rc)
        )
        if hr == 0 and rc.right > rc.left:
            return _rect_from_win(rc)
    _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
    return _rect_from_win(rc)


def _is_cloaked(hwnd: int) -> bool:
    cloaked = ctypes.c_int(0)
    hr = _dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    return hr == 0 and cloaked.value != 0


def _is_invisible_layer(hwnd: int, ex_style: int) -> bool:
    if ex_style & _WS_EX_TRANSPARENT:
        return True
    if ex_style & _WS_EX_LAYERED:
        alpha = ctypes.c_ubyte(255)
        flags = wintypes.DWORD(0)
        if _user32.GetLayeredWindowAttributes(
            wintypes.HWND(hwnd), None, ctypes.byref(alpha), ctypes.byref(flags)
        ):
            if flags.value & _LWA_ALPHA and alpha.value == 0:
                return True
    return False


def snapshot_windows() -> list[WindowInfo]:
    """Visible top-level windows of other processes, topmost first."""
    if not _IS_WINDOWS:
        return []
    own_pid = os.getpid()
    found: list[WindowInfo] = []

    def callback(hwnd, _lparam):
        try:
            if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
                return True
            pid = wintypes.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == own_pid or _is_cloaked(hwnd):
                return True
            ex_style = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            if _is_invisible_layer(hwnd, ex_style):
                return True
            rect = _window_rect(hwnd, top_level=True)
            if rect.width() < _MIN_SIZE or rect.height() < _MIN_SIZE:
                return True
            found.append(WindowInfo(int(hwnd), rect, _class_name(hwnd)))
        except Exception:
            pass
        return True

    _user32.EnumWindows(_ENUM_PROC(callback), 0)
    return found


def chain_at(windows: list[WindowInfo], physical: QPoint, live_children: bool = True) -> list[QRect]:
    """Rects under *physical*, from the top-level window down to the deepest control."""
    top = next((w for w in windows if w.rect.contains(physical)), None)
    if top is None:
        return []
    chain = [QRect(top.rect)]
    if not (_IS_WINDOWS and live_children) or not _user32.IsWindow(top.hwnd):
        return chain
    parent = top.hwnd
    for _ in range(8):
        pt = wintypes.POINT(physical.x(), physical.y())
        _user32.ScreenToClient(wintypes.HWND(parent), ctypes.byref(pt))
        child = _user32.ChildWindowFromPointEx(wintypes.HWND(parent), pt, _CWP_FLAGS)
        if not child or int(child) == int(parent):
            break
        rect = _window_rect(int(child), top_level=False).intersected(chain[-1])
        if rect.width() >= _MIN_SIZE and rect.height() >= _MIN_SIZE and rect != chain[-1]:
            chain.append(rect)
        parent = int(child)
    return chain


# -- coordinate conversion ----------------------------------------------------

def _screen_physical_rect(screen) -> QRect:
    geometry = screen.geometry()
    dpr = float(screen.devicePixelRatio()) or 1.0
    return QRect(
        geometry.x(),
        geometry.y(),
        int(round(geometry.width() * dpr)),
        int(round(geometry.height() * dpr)),
    )


def logical_to_physical(point: QPoint, screen=None) -> QPoint:
    screen = screen or QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    origin = screen.geometry().topLeft()
    dpr = float(screen.devicePixelRatio()) or 1.0
    return QPoint(
        origin.x() + int(round((point.x() - origin.x()) * dpr)),
        origin.y() + int(round((point.y() - origin.y()) * dpr)),
    )


def screen_for_physical(point: QPoint):
    for screen in QGuiApplication.screens():
        if _screen_physical_rect(screen).contains(point):
            return screen
    return None


def physical_to_logical(point: QPoint, screen=None) -> QPoint:
    screen = screen or screen_for_physical(point) or QGuiApplication.primaryScreen()
    origin = screen.geometry().topLeft()
    dpr = float(screen.devicePixelRatio()) or 1.0
    return QPoint(
        origin.x() + int(round((point.x() - origin.x()) / dpr)),
        origin.y() + int(round((point.y() - origin.y()) / dpr)),
    )


def physical_rect_to_logical(rect: QRect, screen) -> QRect:
    """Convert a physical rect to logical coordinates of *screen*, clipped to it."""
    clipped = rect.intersected(_screen_physical_rect(screen))
    if clipped.isEmpty():
        return QRect()
    top_left = physical_to_logical(clipped.topLeft(), screen)
    bottom_right = physical_to_logical(
        QPoint(clipped.x() + clipped.width(), clipped.y() + clipped.height()), screen
    )
    return QRect(top_left, bottom_right - QPoint(1, 1)).intersected(screen.geometry())
