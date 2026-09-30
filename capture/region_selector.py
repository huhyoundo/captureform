from __future__ import annotations

from PyQt6.QtCore import QObject, QPoint, QPointF, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget


class _ScreenOverlay(QWidget):
    """Dimmed overlay covering exactly one screen.

    One overlay per screen keeps Qt's coordinate mapping consistent with that
    screen's DPI. A single window spanning monitors with different scaling
    gets one device-pixel ratio, so part of the other monitor ends up outside
    the window or mapped to the wrong coordinates (the lower half of a scaled
    monitor could not be selected).
    """

    def __init__(self, owner: "RegionSelector", screen) -> None:
        super().__init__()
        self._owner = owner
        self._screen = screen
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    @property
    def screen_obj(self):
        return self._screen

    def place(self) -> None:
        geometry = self._screen.geometry()
        self.setScreen(self._screen)
        self.setGeometry(geometry)
        self.show()
        # Windows may re-map the window when it first appears; pin it again.
        if self.geometry() != geometry:
            self.setGeometry(geometry)

    def to_global(self, local: QPointF) -> QPoint:
        """Map a local logical position to a global logical point on this screen."""
        geometry = self._screen.geometry()
        x = min(max(int(local.x()), 0), geometry.width())
        y = min(max(int(local.y()), 0), geometry.height())
        return QPoint(geometry.x() + x, geometry.y() + y)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._owner._on_press(self, event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._owner._on_move(self, event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._owner._on_release(self, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self._owner._cancel()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._owner._schedule_focus_check()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 102))

        if self._owner._active_overlay is not self:
            return
        selected = self._owner.current_selection()
        if not selected:
            return

        origin = self._screen.geometry().topLeft()
        local_rect = selected.translated(-origin)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(local_rect, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        pen = QPen(self._owner._border_color)
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashOffset(float(self._owner._dash_offset))
        painter.setPen(pen)
        painter.drawRect(local_rect)

        text = f"{selected.width()} x {selected.height()}"
        metrics = QFontMetrics(self.font())
        text_w = metrics.horizontalAdvance(text) + 12
        text_h = metrics.height() + 8

        current = self._owner._current_global or selected.bottomRight()
        cursor_local = current - origin
        text_pos = QPoint(cursor_local.x() + 14, cursor_local.y() + 14)
        if text_pos.x() + text_w > self.width():
            text_pos.setX(max(0, cursor_local.x() - text_w - 14))
        if text_pos.y() + text_h > self.height():
            text_pos.setY(max(0, cursor_local.y() - text_h - 14))

        text_rect = QRect(text_pos, QPoint(text_pos.x() + text_w, text_pos.y() + text_h))
        painter.fillRect(text_rect, QColor(24, 24, 24, 220))
        painter.setPen(QColor("#F2F4F8"))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignCenter), text)


class RegionSelector(QObject):
    """Region selection across all screens, one overlay window per screen.

    A selection is confined to the screen where the drag started, so its
    global logical rect always maps onto a single screen's DPI.
    """

    region_selected = pyqtSignal(QRect)
    cancelled = pyqtSignal()

    def __init__(self, border_color: str = "#00AAFF") -> None:
        super().__init__()
        self._border_color = QColor(border_color)
        self._overlays: list[_ScreenOverlay] = []
        self._active_overlay: _ScreenOverlay | None = None
        self._start_global: QPoint | None = None
        self._current_global: QPoint | None = None
        self._dragging = False
        self._closed = False
        self._dash_offset = 0
        self.selected_screen = None

        self._dash_timer = QTimer(self)
        self._dash_timer.setInterval(70)
        self._dash_timer.timeout.connect(self._tick_dash)

        self._focus_timer = QTimer(self)
        self._focus_timer.setSingleShot(True)
        self._focus_timer.setInterval(120)
        self._focus_timer.timeout.connect(self._check_focus)

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self._closed = False
        for overlay in self._overlays:
            overlay.close()
        self._overlays = [_ScreenOverlay(self, screen) for screen in QApplication.screens()]
        for overlay in self._overlays:
            overlay.place()
        self._focus_initial()
        QTimer.singleShot(0, self._focus_initial)
        self._dash_timer.start()

    def close(self) -> None:
        self._teardown()

    def overlays(self) -> list[QWidget]:
        return list(self._overlays)

    def _focus_initial(self) -> None:
        if self._closed or not self._overlays:
            return
        cursor_screen = QGuiApplication.screenAt(QCursor.pos())
        target = next(
            (o for o in self._overlays if o.screen_obj is cursor_screen),
            self._overlays[0],
        )
        target.raise_()
        target.activateWindow()
        target.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _teardown(self) -> None:
        self._closed = True
        self._dash_timer.stop()
        self._focus_timer.stop()
        if self._dragging and self._active_overlay is not None:
            self._active_overlay.releaseMouse()
        self._dragging = False
        for overlay in self._overlays:
            overlay.hide()
            overlay.close()
        self._overlays = []
        self._active_overlay = None

    def _tick_dash(self) -> None:
        self._dash_offset = (self._dash_offset + 1) % 12
        if self._active_overlay is not None:
            self._active_overlay.update()

    # -- selection -------------------------------------------------------
    def current_selection(self) -> QRect | None:
        if not self._start_global or not self._current_global:
            return None
        start, end = self._start_global, self._current_global
        rect = QRect(
            min(start.x(), end.x()),
            min(start.y(), end.y()),
            abs(end.x() - start.x()),
            abs(end.y() - start.y()),
        )
        if rect.width() < 2 or rect.height() < 2:
            return None
        return rect

    def _on_press(self, overlay: _ScreenOverlay, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            previous = self._active_overlay
            self._active_overlay = overlay
            self._dragging = True
            overlay.grabMouse()
            point = overlay.to_global(event.position())
            self._start_global = point
            self._current_global = point
            if previous is not None and previous is not overlay:
                previous.update()
            overlay.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel()

    def _on_move(self, overlay: _ScreenOverlay, event: QMouseEvent) -> None:
        if not self._dragging or overlay is not self._active_overlay:
            return
        self._current_global = overlay.to_global(event.position())
        overlay.update()

    def _on_release(self, overlay: _ScreenOverlay, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._dragging or overlay is not self._active_overlay:
            return

        self._dragging = False
        overlay.releaseMouse()
        self._current_global = overlay.to_global(event.position())
        rect = self.current_selection()
        if rect is None:
            self._cancel()
            return
        if self._closed:
            return

        self.selected_screen = overlay.screen_obj
        self._teardown()
        self.region_selected.emit(rect)
        self.deleteLater()

    # -- cancel / focus --------------------------------------------------
    def _schedule_focus_check(self) -> None:
        if not self._closed:
            self._focus_timer.start()

    def _check_focus(self) -> None:
        # Moving between our own overlays is fine. Losing focus to another
        # application cancels, but never in the middle of a drag.
        if self._closed or self._dragging:
            return
        active = QApplication.activeWindow()
        if active is not None and active in self._overlays:
            return
        self._cancel()

    def _cancel(self) -> None:
        if self._closed:
            return
        self._teardown()
        self.cancelled.emit()
        self.deleteLater()


class CaptureActionToolbar(QWidget):
    action_selected = pyqtSignal(str)

    # Actions that work on the still screenshot. After a recording they
    # would save or copy a second, stale file, so they are hidden then.
    _STILL_IMAGE_ACTIONS = ("copy", "pin", "ocr", "edit", "save")

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

    def set_recording_result_mode(self, enabled: bool) -> None:
        """Show only the actions that make sense for a finished recording."""
        for key in self._STILL_IMAGE_ACTIONS:
            button = self._buttons.get(key)
            if button is not None:
                button.setVisible(not enabled)
        self.adjustSize()

    def show_mp4_button(self, visible: bool) -> None:
        mp4_button = self._buttons.get("mp4")
        if mp4_button is not None:
            mp4_button.setVisible(visible)
        self.adjustSize()

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
