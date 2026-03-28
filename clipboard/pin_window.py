from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QMenu, QWidget


class PinWindow(QWidget):
    """Always-on-top floating window that displays a pinned screenshot."""

    closed = pyqtSignal(object)  # emits self when closed

    MIN_SIZE = 80
    MAX_SIZE = 2000
    SCALE_STEP = 0.1
    BORDER = 3

    def __init__(
        self,
        image: QPixmap,
        file_path: Path | str | None = None,
        opacity: float = 1.0,
    ) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._original_pixmap = image
        self._pixmap = image
        self._file_path = str(file_path) if file_path else None
        self._scale = 1.0
        self._drag_pos: QPoint | None = None

        self.setWindowOpacity(opacity)
        self._update_size()

    # ── sizing ──────────────────────────────────────────────

    def _update_size(self) -> None:
        w = max(self.MIN_SIZE, int(self._original_pixmap.width() * self._scale))
        h = max(self.MIN_SIZE, int(self._original_pixmap.height() * self._scale))
        w = min(w, self.MAX_SIZE)
        h = min(h, self.MAX_SIZE)
        self._pixmap = self._original_pixmap.scaled(
            QSize(w, h),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        b = self.BORDER * 2
        self.setFixedSize(self._pixmap.width() + b, self._pixmap.height() + b)

    def _set_scale(self, scale: float) -> None:
        orig_w = self._original_pixmap.width()
        min_scale = self.MIN_SIZE / max(orig_w, 1)
        max_scale = self.MAX_SIZE / max(orig_w, 1)
        self._scale = max(min_scale, min(scale, max_scale))
        self._update_size()
        self.update()

    # ── paint ───────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # border
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.black)
        painter.drawRoundedRect(self.rect(), 4, 4)

        # image
        b = self.BORDER
        painter.drawPixmap(b, b, self._pixmap)

    # ── drag to move ────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None

    # ── double-click to reset size ──────────────────────────

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_scale(1.0)

    # ── wheel to resize ────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta > 0:
            self._set_scale(self._scale + self.SCALE_STEP)
        elif delta < 0:
            self._set_scale(self._scale - self.SCALE_STEP)
        event.accept()

    # ── right-click context menu ────────────────────────────

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)

        copy_action = QAction("Copy image", self)
        copy_action.triggered.connect(self._copy_image)
        menu.addAction(copy_action)

        if self._file_path:
            path_action = QAction("Copy path", self)
            path_action.triggered.connect(self._copy_path)
            menu.addAction(path_action)

        menu.addSeparator()

        # opacity submenu
        opacity_menu = menu.addMenu("Opacity")
        for pct in (100, 80, 60, 40, 20):
            action = QAction(f"{pct}%", self)
            action.triggered.connect(lambda _checked=False, p=pct: self.setWindowOpacity(p / 100))
            opacity_menu.addAction(action)

        menu.addSeparator()

        reset_action = QAction("Reset size", self)
        reset_action.triggered.connect(lambda: self._set_scale(1.0))
        menu.addAction(reset_action)

        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        menu.addAction(close_action)

        menu.exec(event.globalPos())

    def _copy_image(self) -> None:
        from PyQt6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        clipboard.setPixmap(self._original_pixmap)

    def _copy_path(self) -> None:
        if not self._file_path:
            return
        from PyQt6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        clipboard.setText(self._file_path)

    # ── close ───────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self.closed.emit(self)
        super().closeEvent(event)
