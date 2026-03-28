from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget


class RegionSelector(QWidget):
    region_selected = pyqtSignal(QRect)
    cancelled = pyqtSignal()

    def __init__(self, border_color: str = "#00AAFF") -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        self._start_global: QPoint | None = None
        self._current_global: QPoint | None = None
        self._dragging = False
        self._closed = False
        self._dash_offset = 0
        self._border_color = QColor(border_color)

        self._dash_timer = QTimer(self)
        self._dash_timer.setInterval(70)
        self._dash_timer.timeout.connect(self._tick_dash)

        self._set_virtual_geometry()

    def start(self) -> None:
        self._closed = False
        self._set_virtual_geometry()
        self.show()
        self._ensure_focus()
        QTimer.singleShot(0, self._ensure_focus)
        self._dash_timer.start()

    def _ensure_focus(self) -> None:
        if self._closed:
            return
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _set_virtual_geometry(self) -> None:
        geometry = QRect()
        for screen in QApplication.screens():
            geometry = geometry.united(screen.geometry())
        self.setGeometry(geometry)

    def _tick_dash(self) -> None:
        self._dash_offset = (self._dash_offset + 1) % 12
        self.update()

    def current_selection(self) -> QRect | None:
        if not self._start_global or not self._current_global:
            return None
        rect = QRect(self._start_global, self._current_global).normalized()
        if rect.width() < 2 or rect.height() < 2:
            return None
        return rect

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.grabMouse()
            point = event.globalPosition().toPoint()
            self._start_global = point
            self._current_global = point
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            return
        self._current_global = event.globalPosition().toPoint()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._dragging:
            return

        self._dragging = False
        self.releaseMouse()
        self._current_global = event.globalPosition().toPoint()
        rect = self.current_selection()
        if rect is None:
            self._cancel()
            return

        if self._closed:
            return
        self._closed = True
        self._dash_timer.stop()
        self.hide()
        self.region_selected.emit(rect)
        self.deleteLater()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self._cancel()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        # Don't cancel while dragging — focus can be briefly stolen by
        # system notifications, taskbar, etc.
        if not self._closed and not self._dragging:
            self._cancel()
        super().focusOutEvent(event)

    def _cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._dragging:
            self._dragging = False
            self.releaseMouse()
        self._dash_timer.stop()
        self.hide()
        self.cancelled.emit()
        self.deleteLater()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), QColor(0, 0, 0, 102))

        selected = self.current_selection()
        if not selected:
            return

        local_rect = QRect(
            self.mapFromGlobal(selected.topLeft()),
            self.mapFromGlobal(selected.bottomRight()),
        ).normalized()

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(local_rect, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        pen = QPen(self._border_color)
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashOffset(float(self._dash_offset))
        painter.setPen(pen)
        painter.drawRect(local_rect)

        text = f"{selected.width()} x {selected.height()}"
        metrics = QFontMetrics(self.font())
        text_w = metrics.horizontalAdvance(text) + 12
        text_h = metrics.height() + 8

        cursor_local = self.mapFromGlobal(self._current_global or selected.bottomRight())
        text_pos = QPoint(cursor_local.x() + 14, cursor_local.y() + 14)

        if text_pos.x() + text_w > self.width():
            text_pos.setX(max(0, cursor_local.x() - text_w - 14))
        if text_pos.y() + text_h > self.height():
            text_pos.setY(max(0, cursor_local.y() - text_h - 14))

        text_rect = QRect(text_pos, QPoint(text_pos.x() + text_w, text_pos.y() + text_h))

        painter.fillRect(text_rect, QColor(24, 24, 24, 220))
        painter.setPen(QColor("#F2F4F8"))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignCenter), text)


class CaptureActionToolbar(QWidget):
    action_selected = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        container = QWidget(self)
        container.setObjectName("captureToolbar")

        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self._buttons: dict[str, QPushButton] = {}

        for key, label in [
            ("copy", "Copy"),
            ("pin", "Pin"),
            ("ocr", "OCR"),
            ("record", "Record"),
            ("mp4", "MP4"),
            ("edit", "Edit"),
            ("save", "Save"),
            ("folder", "Folder"),
            ("cancel", "Cancel"),
        ]:
            button = QPushButton(label, container)
            button.setObjectName("toolbarButton")
            button.clicked.connect(lambda _checked=False, k=key: self.action_selected.emit(k))
            layout.addWidget(button)
            self._buttons[key] = button

        self._buttons["mp4"].setVisible(False)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

    def set_recording(self, recording: bool) -> None:
        record_button = self._buttons.get("record")
        if record_button is None:
            return

        record_button.setText("Stop" if recording else "Record")

        if recording:
            self.show_mp4_button(False)

        disable_while_recording = {"copy", "ocr", "edit", "save", "cancel"}
        for key, button in self._buttons.items():
            if key in ("record", "mp4"):
                continue
            button.setEnabled(not recording or key not in disable_while_recording)

    def show_mp4_button(self, visible: bool) -> None:
        mp4_button = self._buttons.get("mp4")
        if mp4_button is not None:
            mp4_button.setVisible(visible)

    def set_record_busy(self, busy: bool) -> None:
        record_button = self._buttons.get("record")
        if record_button is None:
            return
        record_button.setEnabled(not busy)

    def show_near(self, capture_rect: QRect) -> None:
        self.adjustSize()
        target_screen = QGuiApplication.screenAt(capture_rect.center())
        available = (
            target_screen.availableGeometry()
            if target_screen is not None
            else QGuiApplication.primaryScreen().availableGeometry()
        )

        x = capture_rect.left()
        y = capture_rect.bottom() + 8
        if y + self.height() > available.bottom():
            y = capture_rect.top() - self.height() - 8
        if x + self.width() > available.right():
            x = available.right() - self.width()
        if x < available.left():
            x = available.left()
        if y < available.top():
            y = available.top()

        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self.raise_)
