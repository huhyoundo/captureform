from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen

from capture_editor.items.base_item import BaseAnnotationItem


class SpotlightItem(BaseAnnotationItem):
    """Darkens outside selected region to emphasize focus area."""

    def __init__(self, start_pos: QPointF, parent=None):
        super().__init__(parent)
        self.start_pos = start_pos
        self.end_pos = start_pos
        self.overlay_alpha = 80
        self.setZValue(999)

    def set_end_pos(self, pos: QPointF) -> None:
        self.prepareGeometryChange()
        self.end_pos = pos

        min_x = min(self.start_pos.x(), self.end_pos.x())
        min_y = min(self.start_pos.y(), self.end_pos.y())
        max_x = max(self.start_pos.x(), self.end_pos.x())
        max_y = max(self.start_pos.y(), self.end_pos.y())
        self.rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Ignore tiny regions to avoid full-screen sudden dark overlay on single click.
        if self.rect.width() < 8 or self.rect.height() < 8:
            self.draw_selection_overlay(painter)
            return

        if self.scene():
            scene_rect = self.scene().sceneRect()
        else:
            scene_rect = QRectF(-5000, -5000, 10000, 10000)

        full_path = QPainterPath()
        full_path.addRect(scene_rect)

        spotlight_path = QPainterPath()
        spotlight_path.addRoundedRect(self.rect, 8.0, 8.0)

        overlay_path = full_path.subtracted(spotlight_path)

        painter.setBrush(QBrush(QColor(0, 0, 0, self.overlay_alpha)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(overlay_path)

        painter.setPen(QPen(QColor(255, 255, 255, 120), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(spotlight_path)

        self.draw_selection_overlay(painter)
