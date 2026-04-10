from __future__ import annotations

import logging
import webbrowser
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import (
    QByteArray,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Palette (dark, matching app theme)
# ---------------------------------------------------------------------------

_BG         = "#1a1a2e"
_BG_CARD    = "#16213e"
_ACCENT     = "#0f3460"
_HIGHLIGHT  = "#e94560"
_TEXT_PRI   = "#eaeaea"
_TEXT_SEC   = "#9090a8"
_BTN_CLOSE  = "#2a2a4a"
_BTN_MORE   = "#e94560"
_BORDER     = "#2e2e4e"
_RADIUS     = 12          # px, window corner radius

# Popup dimensions
_W = 400
_H = 300
_IMG_H = 150              # height of the ad image banner
_AUTO_CLOSE_MS = 15_000   # auto-close after 15 seconds


# ---------------------------------------------------------------------------
# Background image loader (runs in a QThread)
# ---------------------------------------------------------------------------

class _ImageLoaderThread(QThread):
    """Downloads an image URL and emits the raw bytes when done."""

    loaded = pyqtSignal(bytes)
    failed = pyqtSignal()

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        if not self._url:
            self.failed.emit()
            return
        try:
            req = Request(
                self._url,
                headers={"User-Agent": "Callcap/1.0"},
            )
            with urlopen(req, timeout=6) as resp:
                data = resp.read()
            self.loaded.emit(data)
        except (URLError, OSError) as exc:
            _log.debug("Ad image download failed: %s", exc)
            self.failed.emit()


# ---------------------------------------------------------------------------
# Image banner widget
# ---------------------------------------------------------------------------

class _AdImageBanner(QWidget):
    """Displays the ad image (or a gradient placeholder while loading)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_IMG_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._pixmap: QPixmap | None = None
        self._loading = True

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._loading = False
        self.update()

    def set_failed(self) -> None:
        self._loading = False
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = self.rect()

        if self._pixmap is not None:
            # Scale to fill banner while preserving aspect ratio (crop centre).
            scaled = self._pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = (scaled.width() - rect.width()) // 2
            y_off = (scaled.height() - rect.height()) // 2
            clip_path = QPainterPath()
            clip_path.addRoundedRect(
                float(rect.x()), float(rect.y()),
                float(rect.width()), float(rect.height()),
                float(_RADIUS), float(_RADIUS),
            )
            painter.setClipPath(clip_path)
            painter.drawPixmap(-x_off, -y_off, scaled)
        else:
            # Placeholder gradient
            from PyQt6.QtGui import QLinearGradient
            grad = QLinearGradient(0.0, 0.0, float(rect.width()), float(rect.height()))
            grad.setColorAt(0.0, QColor(_ACCENT))
            grad.setColorAt(1.0, QColor(_BG_CARD))
            painter.fillRect(rect, grad)

            if self._loading:
                painter.setPen(QColor(_TEXT_SEC))
                font = painter.font()
                font.setPointSize(9)
                painter.setFont(font)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "이미지 로딩 중...")

        painter.end()


# ---------------------------------------------------------------------------
# Main popup window
# ---------------------------------------------------------------------------

class AdPopupWindow(QDialog):
    """알캡처-style ad popup for Callcap.

    Signals
    -------
    ad_clicked(ad_id: str)
        Emitted when the user clicks "자세히 보기".
    suppressed_today()
        Emitted when the user checks "오늘 하루 보지 않기" and closes.
    """

    ad_clicked = pyqtSignal(str)
    suppressed_today = pyqtSignal()

    def __init__(
        self,
        ad_data: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ad_data = ad_data
        self._ad_id: str = str(ad_data.get("ad_id", ""))
        self._click_url: str = str(ad_data.get("click_url", ""))
        self._image_url: str = str(ad_data.get("image_url", ""))
        self._user_interacted = False
        self._image_loader: _ImageLoaderThread | None = None

        self._configure_window()
        self._build_ui()
        self._position_bottom_right()
        self._start_image_load()
        self._start_auto_close_timer()

    # ------------------------------------------------------------------
    # Window configuration
    # ------------------------------------------------------------------

    def _configure_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedSize(_W, _H)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        ad_data = self._ad_data

        # Outer container (gives rounded-corner background via paintEvent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        card = QWidget(self)
        card.setObjectName("adCard")
        card.setStyleSheet(
            f"""
            #adCard {{
                background: {_BG};
                border-radius: {_RADIUS}px;
                border: 1px solid {_BORDER};
            }}
            """
        )
        card.setFixedSize(_W, _H)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- Image banner ---------------------------------------------------
        self._banner = _AdImageBanner(card)
        layout.addWidget(self._banner)

        # -- Top-right overlay: "AD" badge + close button -------------------
        # These float over the image; we use absolute positioning.
        ad_badge = QLabel("AD", card)
        ad_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ad_badge.setStyleSheet(
            f"""
            background: rgba(0,0,0,180);
            color: {_TEXT_SEC};
            font-size: 9px;
            font-weight: bold;
            letter-spacing: 1px;
            border-radius: 3px;
            padding: 1px 5px;
            """
        )
        ad_badge.adjustSize()
        ad_badge.move(8, 8)
        ad_badge.raise_()

        close_btn = QPushButton("✕", card)
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: rgba(0,0,0,180);
                color: {_TEXT_PRI};
                border: none;
                border-radius: 12px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background: {_HIGHLIGHT};
            }}
            """
        )
        close_btn.move(_W - 32, 8)
        close_btn.raise_()
        close_btn.clicked.connect(self._on_close_clicked)

        # -- Text area ------------------------------------------------------
        text_widget = QWidget(card)
        text_widget.setStyleSheet(f"background: {_BG_CARD};")
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(14, 10, 14, 8)
        text_layout.setSpacing(4)

        title_label = QLabel(str(ad_data.get("title", "")), text_widget)
        title_label.setStyleSheet(
            f"color: {_TEXT_PRI}; font-size: 13px; font-weight: bold; background: transparent;"
        )
        title_label.setWordWrap(True)
        text_layout.addWidget(title_label)

        desc_label = QLabel(str(ad_data.get("description", "")), text_widget)
        desc_label.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 11px; background: transparent;"
        )
        desc_label.setWordWrap(True)
        text_layout.addWidget(desc_label)

        layout.addWidget(text_widget)

        # -- Bottom bar: sponsor + checkbox + buttons -----------------------
        bottom = QWidget(card)
        bottom.setStyleSheet(f"background: {_BG};")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(14, 6, 14, 10)
        bottom_layout.setSpacing(8)

        sponsor = str(ad_data.get("sponsor", ""))
        if sponsor:
            sponsor_label = QLabel(f"제공: {sponsor}", bottom)
            sponsor_label.setStyleSheet(
                f"color: {_TEXT_SEC}; font-size: 9px; background: transparent;"
            )
            bottom_layout.addWidget(sponsor_label)

        bottom_layout.addStretch()

        self._suppress_cb = QCheckBox("오늘 하루 보지 않기", bottom)
        self._suppress_cb.setStyleSheet(
            f"""
            QCheckBox {{
                color: {_TEXT_SEC};
                font-size: 10px;
                background: transparent;
                spacing: 4px;
            }}
            QCheckBox::indicator {{
                width: 13px;
                height: 13px;
                border-radius: 3px;
                border: 1px solid {_TEXT_SEC};
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                background: {_HIGHLIGHT};
                border-color: {_HIGHLIGHT};
            }}
            """
        )
        bottom_layout.addWidget(self._suppress_cb)

        more_btn = QPushButton("자세히 보기", bottom)
        more_btn.setFixedHeight(28)
        more_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        more_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {_BTN_MORE};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #ff5c75;
            }}
            QPushButton:pressed {{
                background: #c73352;
            }}
            """
        )
        more_btn.clicked.connect(self._on_learn_more_clicked)
        bottom_layout.addWidget(more_btn)

        layout.addWidget(bottom)

        # Store reference to auto-close timer label (shown in close button)
        self._close_btn_ref = close_btn

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def _position_bottom_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(100, 100)
            return
        geo: QRect = screen.availableGeometry()
        margin = 16
        x = geo.right() - _W - margin
        y = geo.bottom() - _H - margin
        self.move(x, y)

    # ------------------------------------------------------------------
    # Image loading
    # ------------------------------------------------------------------

    def _start_image_load(self) -> None:
        if not self._image_url:
            self._banner.set_failed()
            return

        self._image_loader = _ImageLoaderThread(self._image_url)
        self._image_loader.loaded.connect(self._on_image_loaded)
        self._image_loader.failed.connect(self._on_image_failed)
        self._image_loader.finished.connect(self._image_loader.deleteLater)
        self._image_loader.start()

    @pyqtSlot(bytes)
    def _on_image_loaded(self, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(QByteArray(data)):
            self._banner.set_pixmap(pixmap)
        else:
            _log.debug("Could not decode ad image data.")
            self._banner.set_failed()

    @pyqtSlot()
    def _on_image_failed(self) -> None:
        self._banner.set_failed()

    # ------------------------------------------------------------------
    # Auto-close timer
    # ------------------------------------------------------------------

    def _start_auto_close_timer(self) -> None:
        self._remaining_ms = _AUTO_CLOSE_MS
        self._countdown_tick_ms = 1000

        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setInterval(self._countdown_tick_ms)
        self._auto_close_timer.timeout.connect(self._on_auto_close_tick)
        self._auto_close_timer.start()

    @pyqtSlot()
    def _on_auto_close_tick(self) -> None:
        if self._user_interacted:
            self._auto_close_timer.stop()
            # Reset close button text to plain X
            self._close_btn_ref.setText("✕")
            return

        self._remaining_ms -= self._countdown_tick_ms
        secs = max(0, self._remaining_ms // 1000)
        self._close_btn_ref.setText(str(secs) if secs > 0 else "✕")

        if self._remaining_ms <= 0:
            self._auto_close_timer.stop()
            _log.debug("Ad auto-closed after timeout.")
            self._finish_and_close()

    # ------------------------------------------------------------------
    # User interaction
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_learn_more_clicked(self) -> None:
        self._user_interacted = True
        if self._click_url:
            try:
                webbrowser.open(self._click_url)
            except Exception as exc:
                _log.warning("Could not open ad URL: %s", exc)
        self.ad_clicked.emit(self._ad_id)
        self._finish_and_close()

    @pyqtSlot()
    def _on_close_clicked(self) -> None:
        self._user_interacted = True
        self._finish_and_close()

    def _finish_and_close(self) -> None:
        if self._suppress_cb.isChecked():
            self.suppressed_today.emit()
        self.close()

    # ------------------------------------------------------------------
    # Drag to move (frameless window)
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint() - self.pos()
            self._user_interacted = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            hasattr(self, "_drag_start")
            and self._drag_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_start)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start = None
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Rounded-corner background paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        """Paint a drop shadow under the card for depth."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        shadow_color = QColor(0, 0, 0, 80)
        for i in range(1, 5):
            shadow_rect = self.rect().adjusted(i, i, -i, -i)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shadow_color)
            painter.drawRoundedRect(shadow_rect, float(_RADIUS + i), float(_RADIUS + i))

        painter.end()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._image_loader is not None and self._image_loader.isRunning():
            self._image_loader.quit()
            self._image_loader.wait(500)
        super().closeEvent(event)
