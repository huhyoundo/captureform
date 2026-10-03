"""Countdown bubble for delayed capture, and capture exclusion for our own UI."""
from __future__ import annotations

import ctypes
import sys

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter
from PyQt6.QtWidgets import QWidget

_WDA_EXCLUDEFROMCAPTURE = 0x00000011


def exclude_from_capture(widget: QWidget) -> bool:
    """Keep *widget* out of screenshots and recordings (Windows 10 2004+).

    Our toolbar and countdown would otherwise show up inside scroll captures
    and recordings whenever they overlap the captured area.
    """
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winId())
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


class CountdownBubble(QWidget):
    """Small "3, 2, 1" near the cursor that never takes focus.

    Taking focus would close the menu or tooltip the user wants to capture,
    so the window is shown without activation and ignores the mouse.
    """

    finished = pyqtSignal()

    def __init__(self, seconds: int = 3) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedSize(76, 76)
        self._remaining = max(1, int(seconds))
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left(), pos.x() + 24), area.right() - self.width())
        y = min(max(area.top(), pos.y() + 24), area.bottom() - self.height())
        self.move(QPoint(x, y))
        self.show()
        exclude_from_capture(self)
        self._timer.start()

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.hide()
            self.finished.emit()
            self.close()
            return
        self.update()

    def cancel(self) -> None:
        self._timer.stop()
        self.close()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(14, 165, 233, 230))
        painter.drawEllipse(QRectF(4, 4, self.width() - 8, self.height() - 8))
        font = QFont("Malgun Gothic")
        font.setBold(True)
        font.setPixelSize(34)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRectF(self.rect()), int(Qt.AlignmentFlag.AlignCenter), str(self._remaining))
