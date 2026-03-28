from PyQt6.QtGui import QUndoStack, QUndoCommand
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsItem

class ItemAddCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, item: QGraphicsItem, description: str = "Add Item"):
        super().__init__(description)
        self.scene = scene
        self.item = item
        self.is_added = False

    def redo(self):
        if not self.is_added:
            self.scene.addItem(self.item)
            self.is_added = True

    def undo(self):
        if self.is_added:
            self.scene.removeItem(self.item)
            self.is_added = False


class ItemRemoveCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, item: QGraphicsItem, description: str = "Remove Item"):
        super().__init__(description)
        self.scene = scene
        self.item = item
        self.is_added = True

    def redo(self):
        if self.is_added:
            self.scene.removeItem(self.item)
            self.is_added = False

    def undo(self):
        if not self.is_added:
            self.scene.addItem(self.item)
            self.is_added = True


class ItemMoveCommand(QUndoCommand):
    def __init__(self, item: QGraphicsItem, old_pos, new_pos, description: str = "Move Item"):
        super().__init__(description)
        self.item = item
        self.old_pos = old_pos
        self.new_pos = new_pos

    def redo(self):
        self.item.setPos(self.new_pos)

    def undo(self):
        self.item.setPos(self.old_pos)


class ItemGeometryCommand(QUndoCommand):
    def __init__(self, item, old_geom, new_geom, description: str = "Resize Item"):
        super().__init__(description)
        self.item = item
        self.old_geom = old_geom
        self.new_geom = new_geom

    def redo(self):
        from capture_editor.items.base_item import BaseAnnotationItem
        if isinstance(self.item, BaseAnnotationItem):
            self.item.set_rect(self.new_geom)

    def undo(self):
        from capture_editor.items.base_item import BaseAnnotationItem
        if isinstance(self.item, BaseAnnotationItem):
            self.item.set_rect(self.old_geom)
