import os
from pathlib import Path
from PyQt6.QtCore import QRectF, Qt, QSize
from PyQt6.QtGui import QImage, QPainter, QGuiApplication, QClipboard
from PyQt6.QtWidgets import QGraphicsScene, QMessageBox

def export_scene_to_image(scene: QGraphicsScene, background_rect: QRectF = None) -> QImage:
    """
    렌더링 품질을 유지하면서 QGraphicsScene을 QImage로 내보냅니다.
    background_rect가 지정되면 해당 영역에 맞춰 렌더링하고, 없으면 전체 scene의 렌더링 영역을 사용합니다.
    """
    scene.clearSelection() # Deselect items so handles disappear
    
    if background_rect is None:
        source_rect = scene.itemsBoundingRect()
    else:
        source_rect = background_rect
        
    if source_rect.isEmpty():
        source_rect = QRectF(0, 0, 100, 100)

    # 1:1 디스플레이 렌더 품질을 위한 QImage 사이즈 생성
    size = source_rect.size().toSize()
    
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    
    scene.render(painter, target=QRectF(image.rect()), source=source_rect)
    painter.end()
    
    return image

def copy_to_clipboard(image: QImage):
    clipboard = QGuiApplication.clipboard()
    if clipboard:
        clipboard.setImage(image, mode=QClipboard.Mode.Clipboard)

def save_image_to_file(image: QImage, filepath: str) -> bool:
    return image.save(filepath, quality=100)
