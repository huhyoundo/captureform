from __future__ import annotations

from PyQt6.QtCore import QBuffer, QByteArray, QRect
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
import mss


class ScreenCaptureService:
    """Capture a global logical (device-independent) rect of the desktop.

    Qt6 on Windows keeps each screen's top-left in physical pixels and scales
    only its size, so a logical point p on screen s sits at physical
    s.topLeft + (p - s.topLeft) * dpr. Every path below maps per screen with
    that rule; using the logical rect as physical pixels grabs the wrong area
    on scaled monitors (125%, 150%, 200%).
    """

    def capture_region(self, rect: QRect) -> QImage:
        capture_rect = rect.normalized()
        if capture_rect.width() <= 0 or capture_rect.height() <= 0:
            raise ValueError("Capture rect must have positive width and height")

        image = self._capture_region_qt(capture_rect)
        if image is not None and not image.isNull() and not self._is_blank(image):
            return image

        # Qt grabs can come back empty on some GPU/driver setups. Retry with
        # mss using the same per-screen physical mapping. A genuinely uniform
        # area (a blank document) produces the same pixels either way.
        try:
            fallback = self._capture_region_mss(capture_rect)
        except Exception:
            fallback = None
        if fallback is not None and not fallback.isNull():
            return fallback
        if image is not None and not image.isNull():
            return image
        raise RuntimeError("Selected area is not on any screen.")

    @staticmethod
    def _is_blank(image: QImage) -> bool:
        """Return True if the image is essentially blank (one color everywhere)."""
        w, h = image.width(), image.height()
        if w == 0 or h == 0:
            return True
        step_x = max(1, w // 8)
        step_y = max(1, h // 8)
        first = image.pixel(0, 0)
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                if image.pixel(x, y) != first:
                    return False
        return True

    @staticmethod
    def _pieces(rect: QRect):
        """Yield (screen, logical intersection, physical rect) per overlapping screen."""
        for screen in QGuiApplication.screens():
            screen_rect = screen.geometry()
            inter = rect.intersected(screen_rect)
            if inter.isEmpty():
                continue
            dpr = float(screen.devicePixelRatio()) or 1.0
            origin = screen_rect.topLeft()
            px = origin.x() + int(round((inter.x() - origin.x()) * dpr))
            py = origin.y() + int(round((inter.y() - origin.y()) * dpr))
            pw = max(1, int(round(inter.width() * dpr)))
            ph = max(1, int(round(inter.height() * dpr)))
            yield screen, inter, QRect(px, py, pw, ph)

    def _capture_region_qt(self, rect: QRect) -> QImage | None:
        result = QImage(rect.size(), QImage.Format.Format_ARGB32)
        result.fill(0)

        painter = QPainter(result)
        drawn = False
        try:
            for screen, inter, _physical in self._pieces(rect):
                local_rect = inter.translated(-screen.geometry().topLeft())
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

    def _capture_region_mss(self, rect: QRect) -> QImage | None:
        result = QImage(rect.size(), QImage.Format.Format_ARGB32)
        result.fill(0)

        painter = QPainter(result)
        drawn = False
        try:
            with mss.mss() as sct:
                for _screen, inter, physical in self._pieces(rect):
                    shot = sct.grab(
                        {
                            "left": physical.x(),
                            "top": physical.y(),
                            "width": physical.width(),
                            "height": physical.height(),
                        }
                    )
                    piece = QImage(
                        shot.bgra,
                        shot.width,
                        shot.height,
                        shot.width * 4,
                        QImage.Format.Format_RGB32,
                    ).copy()
                    if piece.size() != inter.size():
                        piece = piece.scaled(inter.size())
                    painter.drawImage(inter.topLeft() - rect.topLeft(), piece)
                    drawn = True
        finally:
            painter.end()

        return result if drawn else None

    # -- frozen screens (delayed capture) ----------------------------------
    def grab_screens(self) -> list[tuple[QRect, float, QImage]]:
        """Snapshot every screen now: (logical geometry, dpr, physical image).

        Used by delayed capture so menus and tooltips that close when the
        selection overlay takes focus are still in the picture.
        """
        frozen: list[tuple[QRect, float, QImage]] = []
        for screen in QGuiApplication.screens():
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                continue
            image = pixmap.toImage()
            image.setDevicePixelRatio(1.0)
            frozen.append((QRect(screen.geometry()), float(screen.devicePixelRatio()) or 1.0, image))
        return frozen

    @staticmethod
    def crop_frozen(frozen: list[tuple[QRect, float, QImage]], rect: QRect) -> QImage:
        capture_rect = rect.normalized()
        result = QImage(capture_rect.size(), QImage.Format.Format_ARGB32)
        result.fill(0)
        painter = QPainter(result)
        drawn = False
        try:
            for geometry, dpr, image in frozen:
                inter = capture_rect.intersected(geometry)
                if inter.isEmpty():
                    continue
                sx = image.width() / max(1, geometry.width())
                sy = image.height() / max(1, geometry.height())
                source = QRect(
                    int(round((inter.x() - geometry.x()) * sx)),
                    int(round((inter.y() - geometry.y()) * sy)),
                    max(1, int(round(inter.width() * sx))),
                    max(1, int(round(inter.height() * sy))),
                )
                piece = image.copy(source)
                if piece.size() != inter.size():
                    piece = piece.scaled(inter.size())
                painter.drawImage(inter.topLeft() - capture_rect.topLeft(), piece)
                drawn = True
        finally:
            painter.end()
        if not drawn:
            raise RuntimeError("Selected area is not on any screen.")
        return result

    @staticmethod
    def image_to_png_bytes(image: QImage) -> bytes:
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return bytes(byte_array)
