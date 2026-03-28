from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGraphicsSceneMouseEvent

from capture_editor.items.spotlight_item import SpotlightItem
from capture_editor.tools.base_tool import BaseTool
from capture_editor.utils.history import ItemAddCommand


class SpotlightTool(BaseTool):
    def __init__(self, scene, history_stack):
        super().__init__(scene, history_stack)
        self.current_item = None
        self.min_size = 24

    def handle_press(self, event: QGraphicsSceneMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        # Existing annotation items should stay selectable/movable.
        if self.hit_annotation_item(event) is not None:
            return False

        pos = event.scenePos()
        self.current_item = SpotlightItem(pos)
        self.scene.addItem(self.current_item)
        return True

    def handle_move(self, event: QGraphicsSceneMouseEvent) -> bool:
        if self.current_item is not None:
            self.current_item.set_end_pos(event.scenePos())
            return True
        return False

    def handle_release(self, event: QGraphicsSceneMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        if self.current_item is None:
            return False

        width = self.current_item.rect.width()
        height = self.current_item.rect.height()
        if width < self.min_size or height < self.min_size:
            self.scene.removeItem(self.current_item)
            self.current_item = None
            return True

        cmd = ItemAddCommand(self.scene, self.current_item)
        cmd.is_added = True
        self.history_stack.push(cmd)
        self.current_item = None
        return True
