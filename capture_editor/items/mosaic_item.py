from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen

from capture_editor.items.base_item import BaseAnnotationItem

DEFAULT_BLOCK_SIZE = 12
MIN_BLOCK_SIZE = 4
MAX_BLOCK_SIZE = 40


def pixelate(image: QImage, block_size: int) -> QImage:
    """Return *image* reduced to solid blocks of about block_size pixels.

    Each block is the average colour of the pixels it covers, so the original
    detail (text, faces, numbers) cannot be recovered from the result.
    """
    block = max(1, int(block_size))
    w, h = image.width(), image.height()
    if w <= 0 or h <= 0:
        return image
    small = image.scaled(
        max(1, round(w / block)),
        max(1, round(h / block)),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return small.scaled(
        w,
        h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


class MosaicItem(BaseAnnotationItem):
    """Pixelates the part of the base image that lies under its rectangle.

    The pixels are recomputed from the base image whenever the item moves or
    its block size changes, so moving a mosaic box never smears an earlier
    mosaic or another annotation into it.
    """

    def __init__(self, start_pos: QPointF, block_size: int = DEFAULT_BLOCK_SIZE, parent=None):
        super().__init__(parent)
        self.start_pos = start_pos
        self.end_pos = start_pos
        self.rect = QRectF(start_pos, start_pos)
        self.pen_width = 1.0
        self.block_size = self._clamp_block(block_size)
        self._cache_key: tuple | None = None
        self._cache_image: QImage | None = None
        # Above the screenshot, below arrows, shapes and text.
        self.setZValue(-500)

    @staticmethod
    def _clamp_block(value: int) -> int:
        return max(MIN_BLOCK_SIZE, min(MAX_BLOCK_SIZE, int(value)))

    def set_block_size(self, value: int) -> None:
        value = self._clamp_block(value)
        if value == self.block_size:
            return
        self.block_size = value
        self._cache_key = None
        self.update()

    def set_end_pos(self, pos: QPointF) -> None:
        self.prepareGeometryChange()
        self.end_pos = pos
        min_x = min(self.start_pos.x(), self.end_pos.x())
        min_y = min(self.start_pos.y(), self.end_pos.y())
        max_x = max(self.start_pos.x(), self.end_pos.x())
        max_y = max(self.start_pos.y(), self.end_pos.y())
        self.rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        self._cache_key = None
        self.update()

    def _base_image(self) -> QImage | None:
        scene = self.scene()
        if scene is None:
            return None
        image = getattr(scene, "base_image", None)
        if image is None or image.isNull():
            return None
        return image

    def _source_rect(self, base: QImage) -> QRect:
        scene_rect = self.mapRectToScene(self.rect).toAlignedRect()
        return scene_rect.intersected(base.rect())

    def mosaic_image(self) -> tuple[QRect, QImage] | None:
        """Pixelated pixels for the current position, in base-image coordinates."""
        base = self._base_image()
        if base is None:
            return None
        source = self._source_rect(base)
        if source.isEmpty():
            return None
        key = (source.x(), source.y(), source.width(), source.height(), self.block_size, base.cacheKey())
        if key != self._cache_key or self._cache_image is None:
            self._cache_image = pixelate(base.copy(source), self.block_size)
            self._cache_key = key
        return source, self._cache_image

    def itemChange(self, change, value):
        if change == BaseAnnotationItem.GraphicsItemChange.ItemPositionHasChanged:
            self._cache_key = None
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        result = self.mosaic_image()
        if result is not None:
            source, pixels = result
            target = self.mapRectFromScene(QRectF(source))
            painter.save()
            # Keep hard block edges when the view is zoomed or exported.
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.drawImage(target, pixels)
            painter.restore()

        if self.isSelected() or result is None:
            painter.save()
            painter.setPen(QPen(QColor(255, 255, 255, 160), 1.0, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect)
            painter.restore()

        self.draw_selection_overlay(painter)
