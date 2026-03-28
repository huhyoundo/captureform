from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from clipboard.clipboard_manager import ClipboardEntry, ClipboardManager


class ClipboardHistoryWindow(QWidget):
    """Floating window that shows clipboard history entries."""

    closed = pyqtSignal()

    def __init__(self, clipboard_manager: ClipboardManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.clipboard_manager = clipboard_manager
        self._pending_refresh = False

        self.setWindowTitle("클립보드 히스토리")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(360, 420)
        self.resize(400, 520)
        self._apply_styles()
        self._build_ui()

        self.clipboard_manager.history_changed.connect(self._on_history_changed)
        self._refresh_list()

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget#historyWindow {
                background-color: #171a21;
            }
            QLabel#historyTitle {
                color: #e5e7eb;
                font-size: 13pt;
                font-weight: 600;
            }
            QLabel#historyCount {
                color: #7dd3fc;
                font-size: 9pt;
            }
            QListWidget {
                background-color: #10141c;
                border: 1px solid #303748;
                border-radius: 6px;
                outline: none;
            }
            QListWidget::item {
                border-bottom: 1px solid #232a38;
                padding: 0px;
            }
            QListWidget::item:selected {
                background-color: #1e2d42;
            }
            QListWidget::item:hover {
                background-color: #1a2535;
            }
            QPushButton#clearBtn {
                background-color: #3b1c1c;
                color: #f87171;
                border: 1px solid #5c2a2a;
                padding: 5px 14px;
                border-radius: 5px;
                font-size: 9pt;
            }
            QPushButton#clearBtn:hover {
                background-color: #4c2424;
            }
        """)

    def _build_ui(self) -> None:
        self.setObjectName("historyWindow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("클립보드 히스토리")
        title.setObjectName("historyTitle")
        header.addWidget(title)

        self._count_label = QLabel("")
        self._count_label.setObjectName("historyCount")
        header.addWidget(self._count_label)
        header.addStretch()

        clear_btn = QPushButton("전체 삭제")
        clear_btn.setObjectName("clearBtn")
        clear_btn.clicked.connect(self._on_clear_all)
        header.addWidget(clear_btn)

        layout.addLayout(header)

        # List
        self._list = QListWidget()
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list)

        # Footer hint
        hint = QLabel("더블클릭으로 복사  |  Del 키로 삭제")
        hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

    def _on_history_changed(self) -> None:
        """Only refresh when visible; defer refresh to next event loop to avoid
        destroying widgets while their signals are still being processed."""
        if not self.isVisible():
            self._pending_refresh = True
            return
        QTimer.singleShot(0, self._refresh_list)

    def _refresh_list(self) -> None:
        self._pending_refresh = False
        self._list.clear()
        entries = self.clipboard_manager.history
        self._count_label.setText(f"{len(entries)}개 항목")

        for i, entry in enumerate(entries):
            widget = _EntryWidget(entry, i, self)
            widget.copy_requested.connect(self._on_copy_entry)
            widget.delete_requested.connect(self._on_delete_entry)

            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if 0 <= row < len(self.clipboard_manager.history):
            entry = self.clipboard_manager.history[row]
            self.clipboard_manager.copy_entry(entry)

    def _on_copy_entry(self, index: int) -> None:
        if 0 <= index < len(self.clipboard_manager.history):
            entry = self.clipboard_manager.history[index]
            self.clipboard_manager.copy_entry(entry)

    def _on_delete_entry(self, index: int) -> None:
        self.clipboard_manager.remove_entry(index)

    def _on_clear_all(self) -> None:
        self.clipboard_manager.clear_history()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            current = self._list.currentRow()
            if current >= 0:
                self.clipboard_manager.remove_entry(current)
                return
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)

    def toggle(self) -> None:
        if self.isVisible():
            self.close()
        else:
            if self._pending_refresh:
                self._refresh_list()
            self.show()
            self.raise_()
            self.activateWindow()


class _EntryWidget(QWidget):
    copy_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)

    def __init__(self, entry: ClipboardEntry, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self.setFixedHeight(64)
        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Thumbnail or type icon
        thumb_label = QLabel()
        thumb_label.setFixedSize(48, 48)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if entry.entry_type == "image" and entry.thumbnail is not None:
            pix = QPixmap.fromImage(entry.thumbnail)
            thumb_label.setPixmap(pix.scaled(
                48, 48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            thumb_label.setPixmap(self._text_icon())

        thumb_label.setStyleSheet("border: 1px solid #303748; border-radius: 4px; background-color: #1a1f2b;")
        layout.addWidget(thumb_label)

        # Text preview + timestamp
        info = QVBoxLayout()
        info.setSpacing(2)

        preview = QLabel(entry.preview_text(100))
        preview.setStyleSheet("color: #e5e7eb; font-size: 9pt;")
        preview.setWordWrap(False)
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info.addWidget(preview)

        ts = entry.timestamp.strftime("%H:%M:%S")
        time_label = QLabel(ts)
        time_label.setStyleSheet("color: #6b7280; font-size: 8pt;")
        info.addWidget(time_label)

        layout.addLayout(info, 1)

        # Copy button
        copy_btn = QPushButton("복사")
        copy_btn.setFixedSize(48, 28)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e3a5f;
                color: #7dd3fc;
                border: 1px solid #2d5a8a;
                border-radius: 4px;
                font-size: 8pt;
            }
            QPushButton:hover { background-color: #264b73; }
        """)
        copy_btn.clicked.connect(lambda: self.copy_requested.emit(self._index))
        layout.addWidget(copy_btn)

        # Delete button
        del_btn = QPushButton("×")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #6b7280;
                border: none;
                font-size: 14pt;
                font-weight: bold;
            }
            QPushButton:hover { color: #f87171; }
        """)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._index))
        layout.addWidget(del_btn)

    @staticmethod
    def _text_icon() -> QPixmap:
        pix = QPixmap(48, 48)
        pix.fill(QColor("#1a1f2b"))
        p = QPainter(pix)
        p.setPen(QColor("#6b7280"))
        font = QFont("Segoe UI", 9)
        p.setFont(font)
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "Aa")
        p.end()
        return pix
