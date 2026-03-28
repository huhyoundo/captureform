from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QBrush, QPolygonF, QKeyEvent
from PyQt6.QtWidgets import QGraphicsTextItem

from capture_editor.items.base_item import BaseAnnotationItem


class InlineTextEditor(QGraphicsTextItem):
    def __init__(self, owner, text: str):
        super().__init__(text, owner)
        self._owner = owner

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._owner.set_editing(False)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.clearFocus()
            self._owner.set_editing(False)
            event.accept()
            return

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.clearFocus()
            self._owner.set_editing(False)
            event.accept()
            return

        super().keyPressEvent(event)


class TextItem(BaseAnnotationItem):
    """Text annotation with bubble background."""

    def __init__(
        self,
        text: str,
        font_family: str = "Pretendard",
        font_size: int = 14,
        parent=None,
    ):
        super().__init__(parent)
        self.text_editor = InlineTextEditor(self, text)

        font = QFont(font_family, font_size)
        self.text_editor.setFont(font)
        self.text_editor.setDefaultTextColor(QColor("#FFFFFF"))
        self.text_editor.document().setDocumentMargin(0)
        self.text_editor.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.text_editor.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.text_editor.document().contentsChanged.connect(self._on_text_changed)

        self.bg_color = QColor(0, 0, 0, 150)
        self.text_stroke_color = QColor("#111827")
        self.text_stroke_width = 2
        self.has_bubble_tail = False
        self.padding = 10
        self.color = QColor("#E94560")
        self._editing = False

        self._update_layout()

    def _on_text_changed(self) -> None:
        self._update_layout()

    def _update_layout(self) -> None:
        self.prepareGeometryChange()
        text_rect = self.text_editor.boundingRect()

        width = text_rect.width() + self.padding * 2
        height = text_rect.height() + self.padding * 2
        if self.has_bubble_tail:
            height += 10

        self.rect = QRectF(0, 0, width, height)
        self.text_editor.setPos(self.padding, self.padding)
        self.update()

    def set_font_family(self, family: str) -> None:
        font = self.text_editor.font()
        font.setFamily(family)
        self.text_editor.setFont(font)
        self._update_layout()

    def set_font_size(self, size: int) -> None:
        font = self.text_editor.font()
        font.setPointSize(size)
        self.text_editor.setFont(font)
        self._update_layout()

    def set_text_color(self, color: QColor) -> None:
        self.text_editor.setDefaultTextColor(color)

    def set_style(
        self,
        border_color: QColor,
        fill_color: QColor,
        text_color: QColor,
        text_stroke_color: QColor | None = None,
    ) -> None:
        self.color = QColor(border_color)
        self.bg_color = QColor(fill_color)
        self.text_editor.setDefaultTextColor(QColor(text_color))
        if text_stroke_color is not None:
            self.text_stroke_color = QColor(text_stroke_color)
        self._update_layout()
        self.update()

    def set_tail_enabled(self, enabled: bool) -> None:
        self.has_bubble_tail = bool(enabled)
        self._update_layout()
        self.update()

    def set_editing(self, editing: bool) -> None:
        self._editing = editing
        if editing:
            self.text_editor.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
            self.text_editor.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
            self.text_editor.setFocus(Qt.FocusReason.MouseFocusReason)
            cursor = self.text_editor.textCursor()
            cursor.select(cursor.SelectionType.Document)
            self.text_editor.setTextCursor(cursor)
        else:
            self.text_editor.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            self.text_editor.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.text_editor.clearFocus()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect.contains(event.pos()):
            self.set_editing(True)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.bg_color.alpha() > 0:
            painter.setBrush(QBrush(self.bg_color))
            painter.setPen(QPen(self.color, 2.0))

            tail_height = 10 if self.has_bubble_tail else 0
            base_rect = QRectF(0, 0, self.rect.width(), self.rect.height() - tail_height)
            painter.drawRoundedRect(base_rect, 8.0, 8.0)

            if self.has_bubble_tail:
                center_x = self.rect.width() / 2
                bottom_y = base_rect.bottom()
                poly = QPolygonF(
                    [
                        QPointF(center_x, bottom_y + 10),
                        QPointF(center_x - 10, bottom_y),
                        QPointF(center_x + 10, bottom_y),
                    ]
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPolygon(poly)
                painter.setPen(QPen(self.color, 2.0))
                painter.drawLine(QPointF(center_x - 10, bottom_y), QPointF(center_x, bottom_y + 10))
                painter.drawLine(QPointF(center_x + 10, bottom_y), QPointF(center_x, bottom_y + 10))

        self._draw_text_outline(painter)
        self.draw_selection_overlay(painter)

    def _draw_text_outline(self, painter: QPainter) -> None:
        if self._editing:
            return
        if self.text_stroke_color.alpha() <= 0 or self.text_stroke_width <= 0:
            return

        text = self.text_editor.toPlainText()
        if not text:
            return

        font = self.text_editor.font()
        metrics = QFontMetricsF(font)
        line_height = metrics.lineSpacing()
        ascent = metrics.ascent()

        doc_margin = float(self.text_editor.document().documentMargin())
        x0 = float(self.padding) + doc_margin
        y0 = float(self.padding) + doc_margin + ascent

        painter.save()
        painter.setFont(font)
        painter.setPen(self.text_stroke_color)

        radius = max(1, int(self.text_stroke_width))
        offsets: list[tuple[int, int]] = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                if (dx * dx) + (dy * dy) <= (radius * radius):
                    offsets.append((dx, dy))

        for index, line in enumerate(text.split("\n")):
            if not line:
                continue
            baseline = y0 + (index * line_height)
            for dx, dy in offsets:
                painter.drawText(QPointF(x0 + dx, baseline + dy), line)

        painter.restore()
