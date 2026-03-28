from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QPainter, QPixmap

def get_checkerboard_brush(size: int = 10, color1: str = "#2A2A35", color2: str = "#202028") -> QBrush:
    """Photoshop 스타일의 투명 체크무늬 배경 브러시를 생성합니다."""
    pixmap = QPixmap(size * 2, size * 2)
    
    painter = QPainter(pixmap)
    painter.fillRect(0, 0, size, size, QColor(color1))
    painter.fillRect(size, size, size, size, QColor(color1))
    painter.fillRect(size, 0, size, size, QColor(color2))
    painter.fillRect(0, size, size, size, QColor(color2))
    painter.end()
    
    brush = QBrush(pixmap)
    return brush
