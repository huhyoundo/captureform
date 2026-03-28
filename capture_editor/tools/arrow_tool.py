from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGraphicsSceneMouseEvent
from capture_editor.tools.base_tool import BaseTool
from capture_editor.items.arrow_item import ArrowItem
from capture_editor.utils.history import ItemAddCommand

class ArrowTool(BaseTool):
    def __init__(self, scene, history_stack):
        super().__init__(scene, history_stack)
        self.current_item = None
        
        # Tool properties
        self.current_style = "straight" # straight, handdrawn, pigtail
        self.current_color = Qt.GlobalColor.red
        self.current_width = 4.0

    def handle_press(self, event: QGraphicsSceneMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        # Existing annotation items should stay selectable/movable.
        if self.hit_annotation_item(event) is not None:
            return False

        pos = event.scenePos()
        self.current_item = ArrowItem(pos, self.current_style)
        self.current_item.set_color(self.current_color)
        self.current_item.set_pen_width(self.current_width)
        self.scene.addItem(self.current_item)
        return True

    def handle_move(self, event: QGraphicsSceneMouseEvent) -> bool:
        if self.current_item is not None:
            self.current_item.update_control_point(event.scenePos())
            return True
        return False

    def handle_release(self, event: QGraphicsSceneMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
            
        if self.current_item is not None:
            # push to undo stack
            cmd = ItemAddCommand(self.scene, self.current_item)
            # manually set added to True since it was already added during draw
            cmd.is_added = True 
            self.history_stack.push(cmd)
            self.current_item = None
            return True
        return False
