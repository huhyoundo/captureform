from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from PyQt6.QtCore import Qt, QRectF
from capture_editor.items.base_item import BaseAnnotationItem

class BadgeItem(BaseAnnotationItem):
    """
    1, 2, 3 등 순서를 나타내는 프리미엄 번호 뱃지
    """
    def __init__(self, number: int, pos, parent=None):
        super().__init__(parent)
        self.number = number
        self.radius = 16.0
        self.rect = QRectF(pos.x() - self.radius, pos.y() - self.radius, self.radius * 2, self.radius * 2)
        self.color = QColor("#E94560")
        self.text_color = QColor("#FFFFFF")
        
        # 그림자 효과 적용
        self.enable_neon_glow(True)
        
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        # 뱃지 배경 (원형)
        painter.setBrush(QBrush(self.color))
        painter.setPen(QPen(Qt.GlobalColor.white, 2.0))
        painter.drawEllipse(self.rect)
        
        # 숫자 텍스트
        painter.setPen(self.text_color)
        font = QFont("Pretendard", int(self.radius * 0.9), QFont.Weight.Bold)
        painter.setFont(font)
        
        painter.drawText(self.rect, int(Qt.AlignmentFlag.AlignCenter), str(self.number))

        if self.isSelected():
            painter.setPen(QPen(QColor("#00AAFF"), 1.0, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect().adjusted(2, 2, -2, -2))
