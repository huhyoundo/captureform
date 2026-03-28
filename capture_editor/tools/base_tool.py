from PyQt6.QtWidgets import QGraphicsSceneMouseEvent

class BaseTool:
    """
    모든 드로잉 도구의 기본 인터페이스.
    Event 통과 여부를 boolean으로 반환하여 Scene에서 이벤트를 계속 처리할지 결정합니다.
    """
    def __init__(self, scene, history_stack):
        self.scene = scene
        self.history_stack = history_stack
        self.is_active = False

    def handle_press(self, event: QGraphicsSceneMouseEvent) -> bool:
        return False

    def handle_move(self, event: QGraphicsSceneMouseEvent) -> bool:
        return False

    def handle_release(self, event: QGraphicsSceneMouseEvent) -> bool:
        return False
        
    def activate(self):
        self.is_active = True
        
    def deactivate(self):
        self.is_active = False

    def hit_annotation_item(self, event: QGraphicsSceneMouseEvent):
        """Return annotation item under cursor if present, otherwise None."""
        from capture_editor.items.base_item import BaseAnnotationItem

        for hit in self.scene.items(event.scenePos()):
            cursor = hit
            while cursor is not None:
                if isinstance(cursor, BaseAnnotationItem):
                    return cursor
                cursor = cursor.parentItem()
        return None
