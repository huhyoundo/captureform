from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pathlib import Path

from PyQt6.QtCore import QMimeData, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

try:
    import pyperclip
except ImportError:  # pragma: no cover
    pyperclip = None


ClipboardType = Literal["image", "text"]


@dataclass
class ClipboardEntry:
    entry_type: ClipboardType
    timestamp: datetime
    text: str | None = None
    image: QImage | None = field(default=None, repr=False)
    thumbnail: QImage | None = field(default=None, repr=False)

    def preview_text(self, max_len: int = 120) -> str:
        if self.entry_type == "image" and self.image is not None:
            return f"[Image {self.image.width()}x{self.image.height()}]"
        if self.text:
            t = self.text.replace("\n", " ").strip()
            return t[:max_len] + ("..." if len(t) > max_len else "")
        return ""


def _image_hash(image: QImage) -> str:
    """Fast perceptual hash: scale to 16x16, hash the raw bytes."""
    try:
        small = image.scaled(16, 16)
        ptr = small.bits()
        if ptr is None:
            return ""
        ptr.setsize(small.sizeInBytes())
        return hashlib.md5(bytes(ptr)).hexdigest()
    except Exception:
        return ""


def _make_thumbnail(image: QImage, size: int = 80) -> QImage:
    return image.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class ClipboardManager(QObject):
    history_changed = pyqtSignal()

    def __init__(self, max_history: int = 50, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.max_history = max_history
        self.history: list[ClipboardEntry] = []

        self._last_text: str = ""
        self._last_image_hash: str = ""
        self._suppress_count: int = 0

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.dataChanged.connect(self._on_clipboard_changed)

    def copy_image(self, image: QImage) -> None:
        self._suppress_count += 1
        clipboard = QApplication.clipboard()
        clipboard.setImage(image)
        self._last_image_hash = _image_hash(image)
        self._last_text = ""
        self._add_entry(ClipboardEntry(
            entry_type="image",
            timestamp=datetime.now(),
            image=image.copy(),
            thumbnail=_make_thumbnail(image),
        ))

    def copy_image_with_path(self, image: QImage, file_path: Path | str) -> None:
        """Copy image and its file path to clipboard simultaneously.

        When pasting in a terminal/prompt (text-only), the file path is pasted.
        When pasting in an image-capable app, the image is pasted.
        """
        self._suppress_count += 1
        clipboard = QApplication.clipboard()

        mime = QMimeData()
        mime.setImageData(image)
        mime.setText(str(file_path))

        clipboard.setMimeData(mime)

        self._last_image_hash = _image_hash(image)
        self._last_text = str(file_path)
        self._add_entry(ClipboardEntry(
            entry_type="image",
            timestamp=datetime.now(),
            image=image.copy(),
            thumbnail=_make_thumbnail(image),
            text=str(file_path),
        ))

    def copy_text(self, text: str) -> None:
        self._suppress_count += 1
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        if pyperclip is not None:
            try:
                pyperclip.copy(text)
            except pyperclip.PyperclipException:
                pass
        self._last_text = text
        self._last_image_hash = ""
        self._add_entry(ClipboardEntry(
            entry_type="text",
            timestamp=datetime.now(),
            text=text,
        ))

    def copy_entry(self, entry: ClipboardEntry) -> None:
        """Re-copy a history entry to the system clipboard."""
        if entry.entry_type == "image" and entry.image is not None:
            self._suppress_count += 1
            QApplication.clipboard().setImage(entry.image)
            self._last_image_hash = _image_hash(entry.image)
            self._last_text = ""
        elif entry.entry_type == "text" and entry.text:
            self._suppress_count += 1
            QApplication.clipboard().setText(entry.text)
            if pyperclip is not None:
                try:
                    pyperclip.copy(entry.text)
                except Exception:
                    pass
            self._last_text = entry.text
            self._last_image_hash = ""

    def remove_entry(self, index: int) -> None:
        if 0 <= index < len(self.history):
            self.history.pop(index)
            self.history_changed.emit()

    def clear_history(self) -> None:
        self.history.clear()
        self.history_changed.emit()

    def _add_entry(self, entry: ClipboardEntry) -> None:
        self.history.insert(0, entry)
        if len(self.history) > self.max_history:
            self.history = self.history[:self.max_history]
        self.history_changed.emit()

    def _on_clipboard_changed(self) -> None:
        """Called by Qt's clipboard.dataChanged signal (instant, no polling)."""
        if self._suppress_count > 0:
            self._suppress_count -= 1
            return

        try:
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime is None:
                return

            # Check text FIRST - avoids misclassifying rich-text copies as images
            if mime.hasText():
                text = clipboard.text()
                if text and text != self._last_text:
                    self._last_text = text
                    self._last_image_hash = ""
                    self._add_entry(ClipboardEntry(
                        entry_type="text",
                        timestamp=datetime.now(),
                        text=text,
                    ))
                    return

            if mime.hasImage():
                image = clipboard.image()
                if image is not None and not image.isNull():
                    h = _image_hash(image)
                    if h and h != self._last_image_hash:
                        self._last_image_hash = h
                        self._last_text = ""
                        self._add_entry(ClipboardEntry(
                            entry_type="image",
                            timestamp=datetime.now(),
                            image=image.copy(),
                            thumbnail=_make_thumbnail(image),
                        ))
        except Exception:
            pass
