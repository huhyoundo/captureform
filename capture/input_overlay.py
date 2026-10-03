"""Click ripples and shortcut captions drawn into recording frames.

A small thread polls GetAsyncKeyState (no hooks, no admin) about 100 times a
second while recording. Only shortcuts are captioned: combinations with Ctrl,
Alt or Win, plus a few command keys. Plain typing is never shown, so a
password typed during a recording does not end up in the video.
"""
from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen

from capture import window_finder

CLICK_DURATION = 0.55
CAPTION_DURATION = 1.4

_VK_MOUSE = {0x01: "left", 0x02: "right", 0x04: "middle"}
_VK_CTRL, _VK_ALT, _VK_SHIFT, _VK_LWIN, _VK_RWIN = 0x11, 0x12, 0x10, 0x5B, 0x5C
_COMMAND_KEYS = {
    0x0D: "Enter", 0x1B: "Esc", 0x09: "Tab", 0x08: "Backspace", 0x2E: "Delete",
    0x2D: "Insert", 0x24: "Home", 0x23: "End", 0x21: "PgUp", 0x22: "PgDn",
}
_ARROWS = {0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓"}


def _key_name(vk: int) -> str | None:
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x70 <= vk <= 0x7B:
        return f"F{vk - 0x6F}"
    if vk == 0x20:
        return "Space"
    if vk in _COMMAND_KEYS:
        return _COMMAND_KEYS[vk]
    if vk in _ARROWS:
        return _ARROWS[vk]
    names = {0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
             0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}
    return names.get(vk)


_WATCHED_KEYS = [vk for vk in range(0x08, 0xDF) if _key_name(vk) is not None]


def caption_for(vk: int, ctrl: bool, alt: bool, shift: bool, win: bool) -> str | None:
    """Text to show for a key press, or None for ordinary typing."""
    name = _key_name(vk)
    if name is None:
        return None
    if not (ctrl or alt or win):
        # Without a modifier only command keys and F-keys are worth showing.
        if vk in _COMMAND_KEYS or 0x70 <= vk <= 0x7B:
            return f"Shift + {name}" if shift else name
        return None
    parts = []
    if ctrl:
        parts.append("Ctrl")
    if alt:
        parts.append("Alt")
    if shift:
        parts.append("Shift")
    if win:
        parts.append("Win")
    parts.append(name)
    return " + ".join(parts)


@dataclass
class ClickEvent:
    at: float
    physical: QPoint
    button: str


@dataclass
class CaptionEvent:
    at: float
    text: str


class InputTracker:
    def __init__(self, poll_hz: int = 100) -> None:
        self._interval = 1.0 / max(10, poll_hz)
        self._lock = threading.Lock()
        self._clicks: list[ClickEvent] = []
        self._caption: CaptionEvent | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if sys.platform != "win32" or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="callcap-input", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    # Test hooks and the poller share these.
    def add_click(self, physical: QPoint, button: str = "left", at: float | None = None) -> None:
        with self._lock:
            self._clicks.append(ClickEvent(time.monotonic() if at is None else at, physical, button))
            self._clicks = self._clicks[-20:]

    def add_caption(self, text: str, at: float | None = None) -> None:
        with self._lock:
            self._caption = CaptionEvent(time.monotonic() if at is None else at, text)

    def active(self, now: float) -> tuple[list[ClickEvent], CaptionEvent | None]:
        with self._lock:
            clicks = [c for c in self._clicks if now - c.at < CLICK_DURATION]
            caption = self._caption if self._caption and now - self._caption.at < CAPTION_DURATION else None
        return clicks, caption

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        state = user32.GetAsyncKeyState

        def down(vk: int) -> bool:
            return bool(state(vk) & 0x8000)

        prev = {vk: down(vk) for vk in list(_VK_MOUSE) + _WATCHED_KEYS}
        pt = wintypes.POINT()
        while not self._stop.is_set():
            for vk, name in _VK_MOUSE.items():
                now_down = down(vk)
                if now_down and not prev[vk]:
                    user32.GetCursorPos(ctypes.byref(pt))
                    self.add_click(QPoint(pt.x, pt.y), name)
                prev[vk] = now_down
            ctrl, alt, shift = down(_VK_CTRL), down(_VK_ALT), down(_VK_SHIFT)
            win = down(_VK_LWIN) or down(_VK_RWIN)
            for vk in _WATCHED_KEYS:
                now_down = down(vk)
                if now_down and not prev[vk]:
                    text = caption_for(vk, ctrl, alt, shift, win)
                    if text:
                        self.add_caption(text)
                prev[vk] = now_down
            self._stop.wait(self._interval)


def draw_overlays(image: QImage, rect: QRect, tracker: InputTracker, now: float | None = None,
                  show_clicks: bool = True, show_keys: bool = True) -> None:
    """Draw active click ripples and the caption into a frame of *rect*."""
    now = time.monotonic() if now is None else now
    clicks, caption = tracker.active(now)
    if not (clicks and show_clicks) and not (caption and show_keys):
        return
    sx = image.width() / max(1, rect.width())
    sy = image.height() / max(1, rect.height())
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    try:
        if show_clicks:
            for click in clicks:
                logical = window_finder.physical_to_logical(click.physical)
                if not rect.contains(logical):
                    continue
                t = (now - click.at) / CLICK_DURATION
                radius = (10 + 22 * t) * sx
                alpha = int(230 * (1.0 - t))
                center = QPointF((logical.x() - rect.x()) * sx, (logical.y() - rect.y()) * sy)
                color = QColor("#FF4D5E") if click.button == "left" else QColor("#3B82F6")
                color.setAlpha(alpha)
                painter.setPen(QPen(color, max(2.0, 3.0 * sx)))
                fill = QColor(color)
                fill.setAlpha(alpha // 3)
                painter.setBrush(fill)
                painter.drawEllipse(center, radius, radius)
        if show_keys and caption is not None:
            font = QFont("Malgun Gothic")
            font.setBold(True)
            font.setPixelSize(int(max(14, min(36, image.height() * 0.06))))
            painter.setFont(font)
            metrics = QFontMetrics(font)
            pad_x, pad_y = font.pixelSize(), font.pixelSize() // 2
            w = metrics.horizontalAdvance(caption.text) + pad_x * 2
            h = metrics.height() + pad_y * 2
            w = min(w, image.width() - 8)
            box = QRectF((image.width() - w) / 2, image.height() - h - max(8, image.height() * 0.05), w, h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(17, 24, 39, 215))
            painter.drawRoundedRect(box, h / 3, h / 3)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), caption.text)
    finally:
        painter.end()
