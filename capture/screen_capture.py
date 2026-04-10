from __future__ import annotations

from PyQt6.QtCore import QBuffer, QByteArray, QRect
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
import mss


class ScreenCaptureService:
    def capture_region(self, rect: QRect) -> QImage:
        capture_rect = rect.normalized()
        if capture_rect.width() <= 0 or capture_rect.height() <= 0:
            raise ValueError("Capture rect must have positive width and height")

        # Qt selector/geometry coordinates are device-independent.
        # Capturing with Qt first helps prevent DPI-related offset issues.
        image = self._capture_region_qt(capture_rect)
        if image is not None and not image.isNull() and not self._is_blank(image):
            return image

        return self._capture_region_mss(capture_rect)

    @staticmethod
    def _is_blank(image: QImage) -> bool:
        """Return True if the image is essentially blank (all white/transparent)."""
        w, h = image.width(), image.height()
        if w == 0 or h == 0:
            return True
        # Sample a grid of pixels — fast enough and catches blank captures.
        step_x = max(1, w // 8)
        step_y = max(1, h // 8)
        first = image.pixel(0, 0)
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                if image.pixel(x, y) != first:
                    return False
        return True

    def _capture_region_qt(self, rect: QRect) -> QImage | None:
        screens = QGuiApplication.screens()
        if not screens:
            return None

        result = QImage(rect.size(), QImage.Format.Format_ARGB32)
        result.fill(0)

        painter = QPainter(result)
        drawn = False
        try:
            for screen in screens:
                screen_rect = screen.geometry()
                inter = rect.intersected(screen_rect)
                if inter.isEmpty():
                    continue

                local_rect = inter.translated(-screen_rect.topLeft())
                pixmap = screen.grabWindow(
                    0,
                    int(local_rect.x()),
                    int(local_rect.y()),
                    int(local_rect.width()),
                    int(local_rect.height()),
                )
                if pixmap.isNull():
                    continue

                piece = pixmap.toImage()
                if piece.isNull():
                    continue

                piece.setDevicePixelRatio(1.0)
                if piece.size() != inter.size():
                    piece = piece.scaled(inter.size())

                painter.drawImage(inter.topLeft() - rect.topLeft(), piece)
                drawn = True
        finally:
            painter.end()

        return result if drawn else None

    def _capture_region_mss(self, rect: QRect) -> QImage:
        monitor = {
            "left": int(rect.x()),
            "top": int(rect.y()),
            "width": int(rect.width()),
            "height": int(rect.height()),
        }

        with mss.mss() as sct:
            shot = sct.grab(monitor)

        image = QImage(
            shot.bgra,
            shot.width,
            shot.height,
            shot.width * 4,
            QImage.Format.Format_ARGB32,
        )
        return image.copy()

    @staticmethod
    def image_to_png_bytes(image: QImage) -> bytes:
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return bytes(byte_array)
