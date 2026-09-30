from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGraphicsSceneMouseEvent

from capture_editor.items.mosaic_item import DEFAULT_BLOCK_SIZE, MosaicItem
from capture_editor.tools.base_tool import BaseTool
from capture_editor.utils.history import ItemAddCommand


class MosaicTool(BaseTool):
    """Drag a rectangle to pixelate that part of the screenshot."""

    def __init__(self, scene, history_stack):
        super().__init__(scene, history_stack)
        self.current_item: MosaicItem | None = None
        self.current_block_size = DEFAULT_BLOCK_SIZE
        self.min_size = 4

    def handle_press(self, event: QGraphicsSceneMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        # Clicking an existing annotation selects or moves it instead.
        if self.hit_annotation_item(event) is not None:
            return False

        self.current_item = MosaicItem(event.scenePos(), self.current_block_size)
        self.scene.addItem(self.current_item)
        return True

    def handle_move(self, event: QGraphicsSceneMouseEvent) -> bool:
        if self.current_item is not None:
            self.current_item.set_end_pos(event.scenePos())
            return True
        return False

    def handle_release(self, event: QGraphicsSceneMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton or self.current_item is None:
            return False

        self.current_item.set_end_pos(event.scenePos())
        rect = self.current_item.rect
        if rect.width() < self.min_size or rect.height() < self.min_size:
            self.scene.removeItem(self.current_item)
            self.current_item = None
            return True

        cmd = ItemAddCommand(self.scene, self.current_item, "Mosaic")
        cmd.is_added = True
        self.history_stack.push(cmd)
        self.current_item = None
        return True
