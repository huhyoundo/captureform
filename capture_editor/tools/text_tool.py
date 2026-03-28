from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsSceneMouseEvent, QGraphicsTextItem

from capture_editor.items.text_item import TextItem
from capture_editor.tools.base_tool import BaseTool
from capture_editor.utils.history import ItemAddCommand


class TextTool(BaseTool):
    def __init__(self, scene, history_stack):
        super().__init__(scene, history_stack)
        self.current_font = "Pretendard"
        self.current_size = 24

        self.current_border_color = QColor("#E94560")
        self.current_fill_color = QColor(233, 69, 96, 60)
        self.current_text_color = QColor("#FFFFFF")
        self.current_text_stroke_color = QColor("#111827")
        self.current_has_tail = False

    def handle_press(self, event: QGraphicsSceneMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        # Existing text: select for move/resize. (Double-click enters edit mode.)
        for hit in self.scene.items(event.scenePos()):
            text_item = self._extract_text_item(hit)
            if text_item is not None:
                self.scene.clearSelection()
                text_item.setSelected(True)
                text_item.set_editing(False)
                return False

        pos = event.scenePos()
        item = TextItem("텍스트 입력", self.current_font, self.current_size)
        item.set_style(
            self.current_border_color,
            self.current_fill_color,
            self.current_text_color,
            self.current_text_stroke_color,
        )
        item.set_tail_enabled(self.current_has_tail)
        item.setPos(pos)

        self.scene.addItem(item)

        cmd = ItemAddCommand(self.scene, item)
        cmd.is_added = True
        self.history_stack.push(cmd)

        self.scene.clearSelection()
        item.setSelected(True)
        item.set_editing(True)
        return True

    @staticmethod
    def _extract_text_item(graphics_item):
        cursor = graphics_item
        while cursor is not None:
            if isinstance(cursor, TextItem):
                return cursor
            if isinstance(cursor, QGraphicsTextItem) and isinstance(cursor.parentItem(), TextItem):
                return cursor.parentItem()
            cursor = cursor.parentItem()
        return None
