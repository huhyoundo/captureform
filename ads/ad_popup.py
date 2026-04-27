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
    QLinearGradient,
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
# Palette
# ---------------------------------------------------------------------------

_BG         = "#1a1a2e"
_ACCENT     = "#0f3460"
_HIGHLIGHT  = "#e94560"
_TEXT_PRI   = "#eaeaea"
_TEXT_SEC   = "#9090a8"
_BORDER     = "#2e2e4e"
_RADIUS     = 8

# Popup dimensions – slim horizontal strip (알약-style)
_W = 400
_H = 90
_IMG_H = 70
_AUTO_CLOSE_MS = 15_000


# ---------------------------------------------------------------------------
# Background image loader
# ---------------------------------------------------------------------------

class _ImageLoaderThread(QThread):
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
            req = Request(self._url, headers={"User-Agent": "Callcap/1.0"})
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
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_IMG_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pixmap: QPixmap | None = None
        self._loading = True

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._loading = False
        self.update()

    def set_failed(self) -> None:
        self._loading = False
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.rect()

        if self._pixmap is not None:
            scaled = self._pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = (scaled.width() - rect.width()) // 2
            y_off = (scaled.height() - rect.height()) // 2
            clip = QPainterPath()
            clip.addRoundedRect(
                float(rect.x()), float(rect.y()),
                float(rect.width()), float(rect.height()),
                float(_RADIUS), float(_RADIUS),
            )
            painter.setClipPath(clip)
            painter.drawPixmap(-x_off, -y_off, scaled)
        else:
            grad = QLinearGradient(0.0, 0.0, float(rect.width()), float(rect.height()))
            grad.setColorAt(0.0, QColor(_ACCENT))
            grad.setColorAt(1.0, QColor(_BG))
            painter.fillRect(rect, grad)
            if self._loading:
                painter.setPen(QColor(_TEXT_SEC))
                font = painter.font()
                font.setPointSize(9)
                painter.setFont(font)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "로딩 중...")

        painter.end()


# ---------------------------------------------------------------------------
# Main popup – slim strip
# ---------------------------------------------------------------------------

class AdPopupWindow(QDialog):
    ad_clicked = pyqtSignal(str)
    suppressed_today = pyqtSignal()

    def __init__(self, ad_data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ad_data = ad_data
        self._ad_id: str = str(ad_data.get("ad_id", ""))
        self._click_url: str = str(ad_data.get("click_url", ""))
        self._image_url: str = str(ad_data.get("image_url", ""))
        self._user_interacted = False
        self._image_loader: _ImageLoaderThread | None = None
        self._drag_start = None

        self._configure_window()
        self._build_ui()
        self._position_bottom_right()
        self._start_image_load()
        self._start_auto_close_timer()

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

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        card = QWidget(self)
        card.setObjectName("adCard")
        card.setStyleSheet(
            f"#adCard {{ background: {_BG}; border-radius: {_RADIUS}px; border: 1px solid {_BORDER}; }}"
        )
        card.setFixedSize(_W, _H)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- Clickable image banner (fills most of the popup) ----------------
        self._banner = _AdImageBanner(card)
        self._banner.clicked.connect(self._on_learn_more_clicked)
        layout.addWidget(self._banner)

        # -- Slim bottom bar: checkbox + close ------------------------------
        bottom = QWidget(card)
        bottom.setFixedHeight(_H - _IMG_H)
        bottom.setStyleSheet(f"background: {_BG};")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(8, 0, 4, 0)
        bottom_layout.setSpacing(4)

        ad_badge = QLabel("AD", bottom)
        ad_badge.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 8px; font-weight: bold; background: transparent;"
        )
        bottom_layout.addWidget(ad_badge)

        self._suppress_cb = QCheckBox("오늘 하루 보지 않기", bottom)
        self._suppress_cb.setStyleSheet(
            f"""
            QCheckBox {{ color: {_TEXT_SEC}; font-size: 9px; background: transparent; spacing: 3px; }}
            QCheckBox::indicator {{ width: 11px; height: 11px; border-radius: 2px; border: 1px solid {_TEXT_SEC}; background: transparent; }}
            QCheckBox::indicator:checked {{ background: {_HIGHLIGHT}; border-color: {_HIGHLIGHT}; }}
            """
        )
        bottom_layout.addWidget(self._suppress_cb)

        bottom_layout.addStretch()

        # Countdown / close button
        close_btn = QPushButton("✕", bottom)
        close_btn.setFixedSize(20, 16)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(
            f"""
            QPushButton {{ background: transparent; color: {_TEXT_SEC}; border: none; font-size: 10px; }}
            QPushButton:hover {{ color: {_HIGHLIGHT}; }}
            """
        )
        close_btn.clicked.connect(self._on_close_clicked)
        bottom_layout.addWidget(close_btn)
        self._close_btn_ref = close_btn

        layout.addWidget(bottom)

    def _position_bottom_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(100, 100)
            return
        geo: QRect = screen.availableGeometry()
        margin = 16
        self.move(geo.right() - _W - margin, geo.bottom() - _H - margin)

    # -- Image loading ------------------------------------------------------

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
            self._banner.set_failed()

    @pyqtSlot()
    def _on_image_failed(self) -> None:
        self._banner.set_failed()

    # -- Auto-close timer ---------------------------------------------------

    def _start_auto_close_timer(self) -> None:
        self._remaining_ms = _AUTO_CLOSE_MS
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setInterval(1000)
        self._auto_close_timer.timeout.connect(self._on_auto_close_tick)
        self._auto_close_timer.start()

    @pyqtSlot()
    def _on_auto_close_tick(self) -> None:
        if self._user_interacted:
            self._auto_close_timer.stop()
            self._close_btn_ref.setText("✕")
            return
        self._remaining_ms -= 1000
        secs = max(0, self._remaining_ms // 1000)
        self._close_btn_ref.setText(str(secs) if secs > 0 else "✕")
        if self._remaining_ms <= 0:
            self._auto_close_timer.stop()
            self._finish_and_close()

    # -- User interaction ---------------------------------------------------

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

    # -- Drag ---------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint() - self.pos()
            self._user_interacted = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_start)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start = None
        super().mouseReleaseEvent(event)

    # -- Paint (subtle shadow) ----------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shadow = QColor(0, 0, 0, 60)
        for i in range(1, 4):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shadow)
            painter.drawRoundedRect(
                self.rect().adjusted(i, i, -i, -i),
                float(_RADIUS + i), float(_RADIUS + i),
            )
        painter.end()

    # -- Cleanup ------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._image_loader is not None and self._image_loader.isRunning():
            self._image_loader.quit()
            self._image_loader.wait(500)
        super().closeEvent(event)
