from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF

from capture_editor.items.base_item import BaseAnnotationItem


class ShapeItem(BaseAnnotationItem):
    """Generic shape annotation item."""

    def __init__(self, start_pos: QPointF, shape_type: str = "rect", parent=None):
        super().__init__(parent)
        self.shape_type = shape_type
        self.start_pos = start_pos
        self.end_pos = start_pos
        self.fill_color = QColor(0, 0, 0, 0)

    def set_end_pos(self, pos: QPointF) -> None:
        self.prepareGeometryChange()
        self.end_pos = pos

        min_x = min(self.start_pos.x(), self.end_pos.x())
        min_y = min(self.start_pos.y(), self.end_pos.y())
        max_x = max(self.start_pos.x(), self.end_pos.x())
        max_y = max(self.start_pos.y(), self.end_pos.y())
        self.rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        self.update()

    def set_fill_color(self, color: QColor) -> None:
        self.fill_color = color
        self.update()

    def set_shape_type(self, shape_type: str) -> None:
        self.shape_type = shape_type
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pen = QPen(self.color)
        pen.setWidthF(self.pen_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        if self.shape_type == "line":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(self.start_pos, self.end_pos)
            self.draw_selection_overlay(painter)
            return

        painter.setBrush(QBrush(self.fill_color))

        if self.shape_type == "rect":
            painter.drawRect(self.rect)
        elif self.shape_type == "round_rect":
            radius = min(self.rect.width(), self.rect.height()) * 0.15
            painter.drawRoundedRect(self.rect, min(radius, 18.0), min(radius, 18.0))
        elif self.shape_type == "ellipse":
            painter.drawEllipse(self.rect)
        elif self.shape_type == "diamond":
            cx = self.rect.center().x()
            cy = self.rect.center().y()
            poly = QPolygonF(
                [
                    QPointF(cx, self.rect.top()),
                    QPointF(self.rect.right(), cy),
                    QPointF(cx, self.rect.bottom()),
                    QPointF(self.rect.left(), cy),
                ]
            )
            painter.drawPolygon(poly)
        else:
            painter.drawRect(self.rect)

        self.draw_selection_overlay(painter)
