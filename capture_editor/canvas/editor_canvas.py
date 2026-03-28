from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QWheelEvent, QPainter, QImage, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QGraphicsView, QWidget

from capture_editor.canvas.grid_background import get_checkerboard_brush

class EditorCanvas(QGraphicsView):
    imageDropped = pyqtSignal(str) # File path
    
    def __init__(self, scene, parent: QWidget = None):
        super().__init__(scene, parent)
        
        # 렌더링 최적화 및 고품질 설정
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        
        # 스크롤 최적화
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 투명 배경 체크무늬 설정
        self.setBackgroundBrush(get_checkerboard_brush())
        
        # 드래그 앤 드롭 지원
        self.setAcceptDrops(True)
        
        # 상태 변수
        self._is_panning = False
        self._pan_start_x = 0
        self._pan_start_y = 0
        self.zoom_factor = 1.0
        
    def wheelEvent(self, event: QWheelEvent):
        """마우스 휠로 확대/축소"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier or True: # 항상 휠로 줌인/줌아웃
            zoom_in_factor = 1.15
            zoom_out_factor = 1.0 / zoom_in_factor
            
            # Save the scene pos
            old_pos = self.mapToScene(event.position().toPoint())
            
            if event.angleDelta().y() > 0:
                zoom_factor = zoom_in_factor
            else:
                zoom_factor = zoom_out_factor
                
            self.scale(zoom_factor, zoom_factor)
            self.zoom_factor *= zoom_factor
            
            # Get the new position
            new_pos = self.mapToScene(event.position().toPoint())
            
            # Move scene to old position
            delta = new_pos - old_pos
            self.translate(delta.x(), delta.y())
            
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and event.modifiers() == Qt.KeyboardModifier.AltModifier):
            self._is_panning = True
            self._pan_start_x = event.position().x()
            self._pan_start_y = event.position().y()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_panning:
            dx = event.position().x() - self._pan_start_x
            dy = event.position().y() - self._pan_start_y
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - dx))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - dy))
            self._pan_start_x = event.position().x()
            self._pan_start_y = event.position().y()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            
    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    # 간단히 첫 번째 이미지만 처리
                    if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                        self.imageDropped.emit(file_path)
                        break
            event.acceptProposedAction()
