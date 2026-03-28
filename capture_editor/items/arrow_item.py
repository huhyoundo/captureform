from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen

from capture_editor.items.base_item import BaseAnnotationItem
from capture_editor.utils.math_utils import (
    create_handdrawn_path,
    create_pigtail_arrow_path,
    get_arrowhead_polygon,
)


class ArrowItem(BaseAnnotationItem):
    """Arrow annotation item with multiple styles."""

    def __init__(self, start_pos: QPointF, style: str = "straight", parent=None):
        super().__init__(parent)
        self.start_pos = start_pos
        self.end_pos = start_pos
        self.style = style
        self.arrowhead_style = "triangle"
        self.coil_count = 1

    def set_end_pos(self, pos: QPointF) -> None:
        self.prepareGeometryChange()
        self.end_pos = pos

        min_x = min(self.start_pos.x(), self.end_pos.x())
        min_y = min(self.start_pos.y(), self.end_pos.y())
        max_x = max(self.start_pos.x(), self.end_pos.x())
        max_y = max(self.start_pos.y(), self.end_pos.y())
        self.rect = QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        self.update()

    def update_control_point(self, mouse_pos: QPointF) -> None:
        self.set_end_pos(mouse_pos)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pen = QPen(self.color)
        pen.setWidthF(self.pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        if self.style == "straight":
            painter.drawLine(self.start_pos, self.end_pos)
            arrow_angle = -QLineF(self.start_pos, self.end_pos).angle()
        elif self.style == "handdrawn":
            path = create_handdrawn_path(self.start_pos, self.end_pos, shakiness=self.pen_width * 0.5)
            painter.drawPath(path)
            arrow_angle = -QLineF(self.start_pos, self.end_pos).angle()
        elif self.style == "pigtail":
            path = create_pigtail_arrow_path(self.start_pos, self.end_pos, self.coil_count)
            painter.drawPath(path)
            tangent_start = path.pointAtPercent(0.92)
            if QLineF(tangent_start, self.end_pos).length() > 0.1:
                arrow_angle = -QLineF(tangent_start, self.end_pos).angle()
            else:
                arrow_angle = -QLineF(self.start_pos, self.end_pos).angle()
        else:
            painter.drawLine(self.start_pos, self.end_pos)
            arrow_angle = -QLineF(self.start_pos, self.end_pos).angle()

        if QLineF(self.start_pos, self.end_pos).length() > self.pen_width * 3:
            head_size = self.pen_width * 3.5
            poly = get_arrowhead_polygon(
                self.end_pos,
                arrow_angle,
                size=head_size,
                style=self.arrowhead_style,
            )
            painter.setBrush(QBrush(self.color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(poly)

        self.draw_selection_overlay(painter)
