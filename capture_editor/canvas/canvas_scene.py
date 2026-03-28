from PyQt6.QtWidgets import QGraphicsScene, QGraphicsSceneMouseEvent
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import pyqtSignal

class EditorScene(QGraphicsScene):
    # Signals to communicate with the active tool
    scenePressed = pyqtSignal(QGraphicsSceneMouseEvent)
    sceneMoved = pyqtSignal(QGraphicsSceneMouseEvent)
    sceneReleased = pyqtSignal(QGraphicsSceneMouseEvent)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_image_item = None
        self.active_tool = None
        
    def set_base_image(self, image: QImage):
        """배경이 되는 원본 이미지를 설정합니다."""
        self.clear() # 모든 기존 아이템 제거
        pixmap = QPixmap.fromImage(image)
        self.base_image_item = self.addPixmap(pixmap)
        self.base_image_item.setZValue(-1000) # 가장 뒤로
        self.setSceneRect(self.base_image_item.boundingRect())
        
    def set_active_tool(self, tool):
        self.active_tool = tool
        
    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if self.active_tool and self.active_tool.handle_press(event):
            return # 도구가 이벤트를 처리함
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self.active_tool and self.active_tool.handle_move(event):
            return
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self.active_tool and self.active_tool.handle_release(event):
            return
        super().mouseReleaseEvent(event)
