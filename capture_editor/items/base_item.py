from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsObject


class BaseAnnotationItem(QGraphicsObject):
    """Base class for annotation items (shape/arrow/text/spotlight)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlags(
            QGraphicsObject.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsObject.GraphicsItemFlag.ItemIsMovable
            | QGraphicsObject.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        self.color = QColor("#E94560")
        self.pen_width = 4.0
        self.rect = QRectF(0, 0, 10, 10)
        self._shadow_effect: QGraphicsDropShadowEffect | None = None
        self._close_size = 16.0

    def set_color(self, color: QColor) -> None:
        self.color = color
        self.update()

    def set_pen_width(self, width: float) -> None:
        self.pen_width = width
        self.update()

    def set_rect(self, rect: QRectF) -> None:
        self.prepareGeometryChange()
        self.rect = rect
        self.update()

    def boundingRect(self) -> QRectF:
        margin = self.pen_width + 10.0
        return self.rect.adjusted(-margin, -margin, margin, margin)

    def paint(self, painter: QPainter, option, widget=None):
        # Implemented in derived classes.
        return

    def close_button_rect(self) -> QRectF:
        anchor = self.boundingRect().adjusted(4, 4, -4, -4)
        return QRectF(
            anchor.right() - self._close_size,
            anchor.top(),
            self._close_size,
            self._close_size,
        )

    def draw_selection_overlay(self, painter: QPainter) -> None:
        if not self.isSelected():
            return

        painter.save()

        painter.setPen(QPen(QColor("#00AAFF"), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.boundingRect().adjusted(5, 5, -5, -5))

        close_rect = self.close_button_rect()
        painter.setPen(QPen(QColor("#FFFFFF"), 1.2))
        painter.setBrush(QBrush(QColor(230, 57, 70, 230)))
        painter.drawEllipse(close_rect)
        painter.drawLine(
            QPointF(close_rect.left() + 4, close_rect.top() + 4),
            QPointF(close_rect.right() - 4, close_rect.bottom() - 4),
        )
        painter.drawLine(
            QPointF(close_rect.right() - 4, close_rect.top() + 4),
            QPointF(close_rect.left() + 4, close_rect.bottom() - 4),
        )

        painter.restore()

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.isSelected()
            and self.close_button_rect().contains(event.pos())
        ):
            scene = self.scene()
            if scene is not None:
                scene.removeItem(self)
            event.accept()
            return

        super().mousePressEvent(event)

    def hoverMoveEvent(self, event) -> None:
        if self.isSelected() and self.close_button_rect().contains(event.pos()):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def enable_neon_glow(self, enable: bool) -> None:
        if enable:
            if not self._shadow_effect:
                self._shadow_effect = QGraphicsDropShadowEffect()
                self._shadow_effect.setBlurRadius(20)
                self._shadow_effect.setColor(self.color)
                self._shadow_effect.setOffset(0, 0)
                self.setGraphicsEffect(self._shadow_effect)
            else:
                self._shadow_effect.setColor(self.color)
        else:
            self.setGraphicsEffect(None)
            self._shadow_effect = None
