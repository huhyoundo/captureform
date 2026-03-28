from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from capture.repeat_capture import RepeatDiffResult
from clipboard.clipboard_manager import ClipboardManager
from utils.file_manager import FileManager


class RepeatDiffDialog(QDialog):
    def __init__(
        self,
        diff_result: RepeatDiffResult,
        clipboard: ClipboardManager,
        file_manager: FileManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._result = diff_result
        self._clipboard = clipboard
        self._file_manager = file_manager

        self.setWindowTitle("Repeat Capture Diff")
        self.resize(860, 620)

        title = QLabel("변경 감지 결과")
        title.setObjectName("dialogTitle")

        percent = self._result.changed_ratio * 100.0
        summary = QLabel(
            f"변경 픽셀: {self._result.changed_pixels:,} / {self._result.total_pixels:,} "
            f"({percent:.2f}%)"
        )
        summary.setObjectName("dialogInfo")

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setPixmap(QPixmap.fromImage(self._result.diff_image))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(image_label)

        copy_btn = QPushButton("Copy Diff")
        copy_btn.clicked.connect(self._copy_diff)

        save_btn = QPushButton("Save Diff")
        save_btn.clicked.connect(self._save_diff)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(copy_btn)
        button_row.addWidget(save_btn)
        button_row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(summary)
        layout.addWidget(scroll, 1)
        layout.addLayout(button_row)

    def _copy_diff(self) -> None:
        self._clipboard.copy_image(self._result.diff_image)

    def _save_diff(self) -> None:
        suggested = self._file_manager.get_save_directory() / "SC_diff.png"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Diff Image",
            str(Path(suggested)),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not filename:
            return
        self._result.diff_image.save(filename)
