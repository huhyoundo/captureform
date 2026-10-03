from __future__ import annotations

from PyQt6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from capture import window_finder

# (key, label, width ratio, height ratio). None = free selection.
ASPECT_MODES: list[tuple[str, str, int | None, int | None]] = [
    ("free", "자유", None, None),
    ("9:16", "9:16 숏츠", 9, 16),
    ("16:9", "16:9", 16, 9),
    ("1:1", "1:1", 1, 1),
    ("1200x630", "1200x630 썸네일", 1200, 630),
]
_ASPECT_KEYS = {
    Qt.Key.Key_0: 0, Qt.Key.Key_1: 1, Qt.Key.Key_2: 2, Qt.Key.Key_3: 3, Qt.Key.Key_4: 4,
}
_CLICK_SLOP = 4  # px of movement that still counts as a click
# Alpha 1 is invisible but keeps the overlay hit-testable (see paintEvent).
_HIT_TEST_FILL = QColor(0, 0, 0, 1)
_HOVER_TINT = QColor(0, 0, 0, 34)


def aspect_index(key: str) -> int:
    return next((i for i, mode in enumerate(ASPECT_MODES) if mode[0] == key), 0)


def constrain_to_aspect(start: QPoint, current: QPoint, ratio: tuple[int, int] | None, bounds: QRect) -> QPoint:
    """Move *current* so the rect from *start* keeps *ratio* and stays in *bounds*."""
    if ratio is None:
        return current
    rw, rh = ratio
    dx = current.x() - start.x()
    dy = current.y() - start.y()
    sx = 1 if dx >= 0 else -1
    sy = 1 if dy >= 0 else -1
    w, h = abs(dx), abs(dy)
    if w == 0 and h == 0:
        return current
    # Follow the larger drag direction, derive the other side.
    if w * rh >= h * rw:
        h = round(w * rh / rw)
    else:
        w = round(h * rw / rh)
    # Shrink (keeping the ratio) if the rect would leave the screen.
    max_w = (bounds.right() + 1 - start.x()) if sx > 0 else (start.x() - bounds.left())
    max_h = (bounds.bottom() + 1 - start.y()) if sy > 0 else (start.y() - bounds.top())
    scale = min(1.0, max_w / w if w else 1.0, max_h / h if h else 1.0)
    w = int(w * scale)
    h = int(h * scale)
    return QPoint(start.x() + sx * w, start.y() + sy * h)


class _ScreenOverlay(QWidget):
    """Dimmed overlay covering exactly one screen.

    One overlay per screen keeps Qt's coordinate mapping consistent with that
    screen's DPI. A single window spanning monitors with different scaling
    gets one device-pixel ratio, so part of the other monitor ends up outside
    the window or mapped to the wrong coordinates (the lower half of a scaled
    monitor could not be selected).
    """

    def __init__(self, owner: "RegionSelector", screen, frozen_image=None) -> None:
        super().__init__()
        self._owner = owner
        self._screen = screen
        self._frozen = frozen_image
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

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._owner._on_wheel(event.angleDelta().y())
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            self._owner._cancel()
        elif event.key() in _ASPECT_KEYS:
            event.accept()
            self._owner.set_aspect_index(_ASPECT_KEYS[event.key()])
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._owner._schedule_focus_check()

    # -- painting --------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._frozen is not None:
            painter.drawImage(QRectF(self.rect()), self._frozen)
        dim = QColor(0, 0, 0, 102)
        origin = self._screen.geometry().topLeft()
        owner = self._owner

        selected = owner.current_selection() if owner._active_overlay is self else None
        hover = owner.hover_rect() if owner._hover_overlay is self and not owner._dragging else None
        focus = selected or hover

        if focus is None:
            painter.fillRect(self.rect(), dim)
        else:
            local = focus.translated(-origin)
            # Dim everything except the focus rect (works with a frozen background).
            outside = QRect(self.rect())
            for part in (
                QRect(0, 0, outside.width(), local.top()),
                QRect(0, local.bottom() + 1, outside.width(), outside.height() - local.bottom() - 1),
                QRect(0, local.top(), local.left(), local.height()),
                QRect(local.right() + 1, local.top(), outside.width() - local.right() - 1, local.height()),
            ):
                if part.width() > 0 and part.height() > 0:
                    painter.fillRect(part, dim)
            # Never leave a pixel fully transparent: Windows passes clicks on
            # alpha-0 pixels of a layered window to the window underneath, so
            # a cleared hover area over a maximized window swallowed every
            # click and the selection was cancelled (1.2.0 regression).
            # A frozen background is opaque already, so only the live overlay needs this.
            if selected is not None:
                if self._frozen is None:
                    painter.fillRect(local, _HIT_TEST_FILL)
            else:
                # Hovered window: lighter tint than the rest, still clearly in capture mode.
                painter.fillRect(local, _HOVER_TINT)

            pen = QPen(owner._border_color)
            pen.setWidth(2 if selected is not None else 3)
            if selected is not None:
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setDashOffset(float(owner._dash_offset))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(local)

            if selected is not None:
                text = f"{selected.width()} x {selected.height()}"
                current = owner._current_global or selected.bottomRight()
                anchor = current - origin
            else:
                text = f"{focus.width()} x {focus.height()} · 클릭하면 이 영역 캡처"
                anchor = QPoint(local.left(), local.top() - 30) if local.top() > 40 else local.topLeft()
            self._draw_label(painter, text, anchor)

        self._draw_hud(painter)

    def _draw_label(self, painter: QPainter, text: str, anchor: QPoint) -> None:
        metrics = QFontMetrics(self.font())
        text_w = metrics.horizontalAdvance(text) + 12
        text_h = metrics.height() + 8
        pos = QPoint(anchor.x() + 14, anchor.y() + 14)
        if pos.x() + text_w > self.width():
            pos.setX(max(0, anchor.x() - text_w - 14))
        if pos.y() + text_h > self.height():
            pos.setY(max(0, anchor.y() - text_h - 14))
        rect = QRect(pos.x(), pos.y(), text_w, text_h)
        painter.fillRect(rect, QColor(24, 24, 24, 220))
        painter.setPen(QColor("#F2F4F8"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    def _draw_hud(self, painter: QPainter) -> None:
        """Top-centre help strip: aspect modes and what each gesture does."""
        owner = self._owner
        font = QFont(self.font())
        font.setPointSizeF(max(9.0, font.pointSizeF()))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        chips = [f"{i} {label}" for i, (_k, label, _w, _h) in enumerate(ASPECT_MODES)]
        hint = "드래그: 영역 · 클릭: 창 · 휠: 창/버튼 · Shift: 묶음에 추가 · Esc: 취소"
        pad = 8
        chip_ws = [metrics.horizontalAdvance(c) + 16 for c in chips]
        row_w = max(sum(chip_ws) + pad * (len(chips) - 1), metrics.horizontalAdvance(hint))
        box = QRect(0, 0, row_w + 24, metrics.height() * 2 + 30)
        box.moveTopLeft(QPoint((self.width() - box.width()) // 2, 16))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(17, 24, 39, 225))
        painter.drawRoundedRect(QRectF(box), 10, 10)
        x = box.left() + 12
        y = box.top() + 8
        for i, (chip, cw) in enumerate(zip(chips, chip_ws)):
            r = QRect(x, y, cw, metrics.height() + 6)
            active = i == owner._aspect_index
            painter.setBrush(QColor(owner._border_color) if active else QColor(55, 65, 81))
            painter.drawRoundedRect(QRectF(r), 6, 6)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(r, int(Qt.AlignmentFlag.AlignCenter), chip)
            painter.setPen(Qt.PenStyle.NoPen)
            x += cw + pad
        painter.setPen(QColor("#CBD5E1"))
        painter.drawText(
            QRect(box.left(), y + metrics.height() + 10, box.width(), metrics.height() + 6),
            int(Qt.AlignmentFlag.AlignCenter),
            hint,
        )


class RegionSelector(QObject):
    """Region selection across all screens, one overlay window per screen.

    A selection is confined to the screen where the drag started, so its
    global logical rect always maps onto a single screen's DPI.

    Extras: hover + click picks the window (or, with the wheel, the control)
    under the cursor; number keys lock an aspect ratio; holding Shift when
    finishing sets ``append_requested`` so the caller can bundle captures.
    """

    region_selected = pyqtSignal(QRect)
    cancelled = pyqtSignal()
    aspect_changed = pyqtSignal(str)

    def __init__(
        self,
        border_color: str = "#00AAFF",
        frozen=None,
        windows=None,
        snap_windows: bool = True,
        aspect_mode: str = "free",
    ) -> None:
        super().__init__()
        self._border_color = QColor(border_color)
        self._frozen = frozen  # list of (geometry, dpr, image) or None
        self._windows = windows
        self._snap_windows = snap_windows
        self._aspect_index = aspect_index(aspect_mode)
        self._overlays: list[_ScreenOverlay] = []
        self._active_overlay: _ScreenOverlay | None = None
        self._hover_overlay: _ScreenOverlay | None = None
        self._hover_chain: list[QRect] = []  # logical rects, window first
        self._hover_level = 0
        self._hover_physical: QPoint | None = None
        self._press_global: QPoint | None = None
        self._start_global: QPoint | None = None
        self._current_global: QPoint | None = None
        self._dragging = False
        self._closed = False
        self._dash_offset = 0
        self.selected_screen = None
        self.append_requested = False
        self.picked_window = False

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
        if self._snap_windows and self._windows is None:
            try:
                self._windows = window_finder.snapshot_windows()
            except Exception:
                self._windows = []
        for overlay in self._overlays:
            overlay.close()
        self._overlays = []
        for screen in QApplication.screens():
            frozen_image = None
            if self._frozen:
                frozen_image = next(
                    (img for geo, _dpr, img in self._frozen if geo == screen.geometry()), None
                )
            self._overlays.append(_ScreenOverlay(self, screen, frozen_image))
        for overlay in self._overlays:
            overlay.place()
        self._focus_initial()
        QTimer.singleShot(0, self._focus_initial)
        self._dash_timer.start()
        QTimer.singleShot(0, self._update_hover_from_cursor)

    def close(self) -> None:
        self._teardown()

    def overlays(self) -> list[QWidget]:
        return list(self._overlays)

    @property
    def aspect_mode(self) -> str:
        return ASPECT_MODES[self._aspect_index][0]

    def set_aspect_index(self, index: int) -> None:
        index = max(0, min(len(ASPECT_MODES) - 1, index))
        if index == self._aspect_index:
            return
        self._aspect_index = index
        self.aspect_changed.emit(self.aspect_mode)
        if self._dragging and self._active_overlay and self._start_global and self._current_global:
            self._current_global = self._constrained(self._active_overlay, self._current_global)
        for overlay in self._overlays:
            overlay.update()

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
        self._hover_overlay = None

    def _tick_dash(self) -> None:
        self._dash_offset = (self._dash_offset + 1) % 12
        if self._active_overlay is not None and self._dragging:
            self._active_overlay.update()

    # -- hover / window picking -----------------------------------------
    def hover_rect(self) -> QRect | None:
        if not self._hover_chain:
            return None
        level = max(0, min(self._hover_level, len(self._hover_chain) - 1))
        return self._hover_chain[level]

    def _update_hover_from_cursor(self) -> None:
        if self._closed:
            return
        pos = QCursor.pos()
        overlay = next((o for o in self._overlays if o.screen_obj.geometry().contains(pos)), None)
        if overlay is not None:
            self._update_hover(overlay, pos)

    def _update_hover(self, overlay: _ScreenOverlay, global_logical: QPoint) -> None:
        if not self._snap_windows or not self._windows:
            return
        screen = overlay.screen_obj
        physical = window_finder.logical_to_physical(global_logical, screen)
        if self._hover_physical == physical and self._hover_overlay is overlay:
            return
        previous_window = self._hover_chain[0] if self._hover_chain else None
        live = self._frozen is None  # frozen screens: child windows may be gone
        chain_phys = window_finder.chain_at(self._windows, physical, live_children=live)
        chain = [window_finder.physical_rect_to_logical(r, screen) for r in chain_phys]
        chain = [r for r in chain if r.width() >= 8 and r.height() >= 8]
        old_overlay = self._hover_overlay
        self._hover_overlay = overlay
        self._hover_physical = physical
        if not chain or chain[0] != previous_window:
            self._hover_level = 0
        self._hover_chain = chain
        overlay.update()
        if old_overlay is not None and old_overlay is not overlay:
            old_overlay.update()

    def _on_wheel(self, delta: int) -> None:
        if self._dragging or not self._hover_chain:
            return
        step = 1 if delta < 0 else -1  # wheel down = finer (control), up = whole window
        self._hover_level = max(0, min(len(self._hover_chain) - 1, self._hover_level + step))
        if self._hover_overlay is not None:
            self._hover_overlay.update()

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

    def _constrained(self, overlay: _ScreenOverlay, point: QPoint) -> QPoint:
        _key, _label, rw, rh = ASPECT_MODES[self._aspect_index]
        ratio = (rw, rh) if rw and rh else None
        return constrain_to_aspect(self._start_global, point, ratio, overlay.screen_obj.geometry())

    def _on_press(self, overlay: _ScreenOverlay, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            previous = self._active_overlay
            self._active_overlay = overlay
            self._dragging = True
            overlay.grabMouse()
            point = overlay.to_global(event.position())
            self._press_global = point
            self._start_global = point
            self._current_global = point
            if previous is not None and previous is not overlay:
                previous.update()
            overlay.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._cancel()

    def _on_move(self, overlay: _ScreenOverlay, event: QMouseEvent) -> None:
        point = overlay.to_global(event.position())
        if not self._dragging:
            self._update_hover(overlay, point)
            return
        if overlay is not self._active_overlay:
            return
        self._current_global = self._constrained(overlay, point)
        overlay.update()

    def _on_release(self, overlay: _ScreenOverlay, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._dragging or overlay is not self._active_overlay:
            return

        self._dragging = False
        overlay.releaseMouse()
        point = overlay.to_global(event.position())
        self.append_requested = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        moved = self._press_global is not None and (
            (point - self._press_global).manhattanLength() > _CLICK_SLOP
        )
        rect: QRect | None
        if not moved:
            # A click: take the highlighted window/control, if any.
            hover = self.hover_rect() if self._hover_overlay is overlay else None
            rect = QRect(hover) if hover is not None else None
            self.picked_window = rect is not None
        else:
            self._current_global = self._constrained(overlay, point)
            rect = self.current_selection()
            self.picked_window = False

        if rect is None or rect.width() < 2 or rect.height() < 2:
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
    _STILL_IMAGE_ACTIONS = ("copy", "pin", "ocr", "edit", "save", "scroll")

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
            ("scroll", "Scroll"),
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
        self._buttons["scroll"].setToolTip("선택 영역을 아래로 자동 스크롤하며 한 장으로 이어 붙입니다")

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

        disable_while_recording = {"copy", "ocr", "edit", "save", "cancel", "scroll"}
        for key, button in self._buttons.items():
            if key in ("record", "mp4"):
                continue
            button.setEnabled(not recording or key not in disable_while_recording)

    def set_scrolling(self, scrolling: bool) -> None:
        """While a scroll capture runs only its Stop button stays usable."""
        scroll_button = self._buttons.get("scroll")
        if scroll_button is not None:
            scroll_button.setText("Stop" if scrolling else "Scroll")
        for key, button in self._buttons.items():
            if key == "scroll":
                continue
            button.setEnabled(not scrolling)

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
