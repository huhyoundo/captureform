from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGraphicsSceneMouseEvent
from capture_editor.tools.base_tool import BaseTool
from capture_editor.items.shape_item import ShapeItem
from capture_editor.utils.history import ItemAddCommand

class ShapeTool(BaseTool):
    def __init__(self, scene, history_stack):
        super().__init__(scene, history_stack)
        self.current_item = None
        
        # Tool properties
        self.current_type = "rect" # rect, ellipse
        self.current_stroke_color = Qt.GlobalColor.red
        self.current_fill_color = Qt.GlobalColor.transparent
        self.current_width = 4.0

    def handle_press(self, event: QGraphicsSceneMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        # Existing annotation items should stay selectable/movable.
        if self.hit_annotation_item(event) is not None:
            return False

        pos = event.scenePos()
        self.current_item = ShapeItem(pos, self.current_type)
        self.current_item.set_color(self.current_stroke_color)
        self.current_item.set_fill_color(self.current_fill_color)
        self.current_item.set_pen_width(self.current_width)
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
            
        if self.current_item is not None:
            cmd = ItemAddCommand(self.scene, self.current_item)
            cmd.is_added = True
            self.history_stack.push(cmd)
            self.current_item = None
            return True
        return False
