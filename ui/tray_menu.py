from __future__ import annotations

import time
from typing import Callable

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


class TrayMenuController(QObject):
    region_capture_requested = pyqtSignal()
    repeat_capture_requested = pyqtSignal()
    open_save_folder_requested = pyqtSignal()
    clipboard_history_requested = pyqtSignal()
    startup_toggled = pyqtSignal(bool)
    quit_requested = pyqtSignal()

    def __init__(
        self,
        app_name: str = "SuperCapture",
        region_hotkey: str = "ctrl+shift+c",
        repeat_hotkey: str = "ctrl+shift+r",
        clipboard_hotkey: str = "ctrl+alt+v",
        startup_enabled: bool = False,
    ) -> None:
        super().__init__()
        self._message_click_handler: Callable[[], None] | None = None
        self._message_click_token = 0
        self._ignore_activation_until = 0.0
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self._make_icon())

        region_label = self._display_hotkey(region_hotkey)
        repeat_label = self._display_hotkey(repeat_hotkey)
        clipboard_label = self._display_hotkey(clipboard_hotkey)
        self.tray.setToolTip(f"{app_name} - {region_label} / {repeat_label}")

        menu = QMenu()

        region_action = QAction(f"Region Capture\t{region_label}", self)
        region_action.triggered.connect(self.region_capture_requested.emit)
        menu.addAction(region_action)

        repeat_action = QAction(f"Repeat Last\t{repeat_label}", self)
        repeat_action.triggered.connect(self.repeat_capture_requested.emit)
        menu.addAction(repeat_action)

        menu.addSeparator()

        clipboard_action = QAction(f"클립보드 히스토리\t{clipboard_label}", self)
        clipboard_action.triggered.connect(self.clipboard_history_requested.emit)
        menu.addAction(clipboard_action)

        menu.addSeparator()

        folder_action = QAction("Open Save Folder", self)
        folder_action.triggered.connect(self.open_save_folder_requested.emit)
        menu.addAction(folder_action)

        menu.addSeparator()

        self._startup_action = QAction("Windows 시작 시 자동 실행", self)
        self._startup_action.setCheckable(True)
        self._startup_action.setChecked(startup_enabled)
        self._startup_action.toggled.connect(self.startup_toggled.emit)
        menu.addAction(self._startup_action)

        menu.addSeparator()

        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.messageClicked.connect(self._on_message_clicked)

    def set_startup_checked(self, checked: bool) -> None:
        self._startup_action.blockSignals(True)
        self._startup_action.setChecked(checked)
        self._startup_action.blockSignals(False)

    def show(self) -> None:
        self.tray.show()

    def show_message(
        self,
        title: str,
        message: str,
        on_click: Callable[[], None] | None = None,
        duration_ms: int = 2500,
    ) -> None:
        if on_click is not None:
            self._message_click_handler = on_click
            self._message_click_token += 1
            token = self._message_click_token
            # Keep the handler briefly to survive event-order races.
            QTimer.singleShot(max(1000, int(duration_ms)) + 1200, lambda t=token: self._expire_click_handler(t))
        self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, duration_ms)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if time.monotonic() < self._ignore_activation_until:
                return
            self.region_capture_requested.emit()

    def _on_message_clicked(self) -> None:
        # Some Windows shells emit tray activation alongside messageClicked.
        self._ignore_activation_until = time.monotonic() + 1.0
        handler = self._message_click_handler
        self._message_click_handler = None
        self._message_click_token += 1
        if handler is None:
            return
        try:
            handler()
        except Exception:
            pass

    def _expire_click_handler(self, token: int) -> None:
        if token != self._message_click_token:
            return
        self._message_click_handler = None

    @staticmethod
    def _display_hotkey(raw: str) -> str:
        if not raw:
            return ""
        parts = [p.strip() for p in raw.split("+") if p.strip()]
        return "+".join(part.capitalize() if len(part) > 1 else part.upper() for part in parts)

    @staticmethod
    def _make_icon() -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#0EA5E9"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawRect(20, 20, 24, 18)
        painter.drawLine(20, 42, 32, 52)
        painter.drawLine(44, 42, 32, 52)
        painter.end()
        return QIcon(pixmap)
