from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from clipboard.clipboard_manager import ClipboardManager


class OCRResultDialog(QDialog):
    def __init__(self, text: str, clipboard: ClipboardManager, parent=None) -> None:
        super().__init__(parent)
        self._clipboard = clipboard
        self.setWindowTitle("OCR Result")
        self.setModal(False)
        self.resize(680, 460)

        title = QLabel("OCR 결과")
        title.setObjectName("dialogTitle")

        info = QLabel("클립보드에 자동 복사되었습니다.")
        info.setObjectName("dialogInfo")

        self.text_edit = QTextEdit(self)
        self.text_edit.setPlainText(text)

        copy_btn = QPushButton("Copy Again")
        copy_btn.clicked.connect(self.copy_text)

        save_btn = QPushButton("Save as .txt")
        save_btn.clicked.connect(self.save_text)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(copy_btn)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(info)
        layout.addWidget(self.text_edit, 1)
        layout.addLayout(btn_layout)

    def copy_text(self) -> None:
        self._clipboard.copy_text(self.text_edit.toPlainText())

    def save_text(self) -> None:
        suggested = Path.home() / "Documents" / "supercapture_ocr.txt"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save OCR Text",
            str(suggested),
            "Text Files (*.txt);;All Files (*.*)",
        )
        if not filename:
            return
        Path(filename).write_text(self.text_edit.toPlainText(), encoding="utf-8")
