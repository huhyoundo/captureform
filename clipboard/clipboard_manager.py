from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
import time
from datetime import datetime
from typing import Literal
from urllib.parse import unquote, urlparse

from pathlib import Path

_log = logging.getLogger(__name__)

from PyQt6.QtCore import QMimeData, QObject, Qt, QTimer, QUrl, pyqtSignal
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


# How long after a capture an accidental terminal selection may be undone.
_RESTORE_WINDOW_SEC = 30 * 60

# Box drawing, block elements and the Claude Code prompt arrow. A selection made
# of nothing else is a mis-click on a TUI border, never something to paste.
_BORDER_CHARS = {chr(c) for c in range(0x2500, 0x25A0)} | {"❯", "•", "·"}


def is_accidental_selection(text: str) -> bool:
    """True for clipboard text that only an accidental TUI selection produces.

    Claude Code's fullscreen mode copies on select. Clicking into its pane to
    paste a screenshot easily drags across the input box border, which puts
    "────" (or an empty selection) on the clipboard and replaces the capture.
    """
    stripped = "".join(ch for ch in text if not ch.isspace())
    if not stripped:
        return True
    return all(ch in _BORDER_CHARS for ch in stripped)


def _make_thumbnail(image: QImage, size: int = 80) -> QImage:
    return image.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class ClipboardManager(QObject):
    history_changed = pyqtSignal()
    file_drop_requested = pyqtSignal(str)  # emits file path for popup

    def __init__(self, max_history: int = 50, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.max_history = max_history
        self.history: list[ClipboardEntry] = []

        self._last_text: str = ""
        self._last_image_hash: str = ""
        self._suppress_count: int = 0
        self._last_enriched_path: str = ""  # prevents file:/// re-enrichment loop
        # What Callcap itself last put on the clipboard (capture or recording),
        # kept so an accidental terminal selection right after can be undone.
        self._own_copy: dict | None = None

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
        mime.setUrls([QUrl.fromLocalFile(str(file_path))])

        clipboard.setMimeData(mime)
        self._own_copy = {"kind": "image_with_path", "image": image.copy(), "path": str(file_path), "at": time.time()}

        self._last_image_hash = _image_hash(image)
        self._last_text = str(file_path)
        self._add_entry(ClipboardEntry(
            entry_type="image",
            timestamp=datetime.now(),
            image=image.copy(),
            thumbnail=_make_thumbnail(image),
            text=str(file_path),
        ))

    def copy_file_path(self, file_path: Path | str) -> None:
        """Copy a file as path text plus a file URL.

        Terminals and prompts paste the path; Explorer and messengers paste
        the file itself (Qt maps the URL to CF_HDROP on Windows).
        """
        self._suppress_count += 1
        clipboard = QApplication.clipboard()

        mime = QMimeData()
        mime.setText(str(file_path))
        mime.setUrls([QUrl.fromLocalFile(str(file_path))])
        clipboard.setMimeData(mime)
        self._own_copy = {"kind": "file_path", "path": str(file_path), "at": time.time()}

        self._last_text = str(file_path)
        self._last_image_hash = ""
        self._add_entry(ClipboardEntry(
            entry_type="text",
            timestamp=datetime.now(),
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

    @staticmethod
    def _set_cf_hdrop(file_path: str) -> bool:
        """Set CF_HDROP on the Windows clipboard using win32clipboard."""
        import struct
        try:
            import win32clipboard
        except ImportError:
            _log.error("win32clipboard not available")
            return False
        try:
            path_w = file_path.replace("/", "\\")
            encoded = path_w.encode("utf-16-le") + b"\x00\x00"
            encoded += b"\x00\x00"
            dropfiles = struct.pack("IiiII", 20, 0, 0, 0, 1)
            data = dropfiles + encoded

            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_HDROP, data)
            win32clipboard.CloseClipboard()
            return True
        except Exception as e:
            _log.error("win32clipboard CF_HDROP failed: %s", e)
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            return False

    def _try_enrich_file_url(self, text: str) -> bool:
        """Detect file:/// URLs and schedule CF_HDROP via deferred call."""
        stripped = text.strip()
        if not stripped.startswith("file:///"):
            return False
        try:
            parsed = urlparse(stripped)
            local_path = unquote(parsed.path)
            if len(local_path) >= 3 and local_path[0] == "/" and local_path[2] == ":":
                local_path = local_path[1:]
            path = Path(local_path)
            resolved = str(path)
            _log.info("file:/// detected -> path=%s exists=%s", path, path.exists())
            if not path.exists():
                return False
            # Skip if we already enriched this exact file path (prevents
            # feedback loop when URL-encoded vs decoded forms alternate)
            if resolved == self._last_enriched_path:
                _log.debug("skipping re-enrichment for same path: %s", resolved)
                return True
            self._last_enriched_path = resolved
            # Defer CF_HDROP to let Qt release the clipboard first
            self._suppress_count += 1
            QTimer.singleShot(150, lambda: self._deferred_set_hdrop(resolved))
            self._last_text = stripped
            self._last_image_hash = ""
            self._add_entry(ClipboardEntry(
                entry_type="text",
                timestamp=datetime.now(),
                text=stripped,
            ))
            return True
        except Exception as e:
            _log.error("enrich failed: %s", e)
            return False

    def _deferred_set_hdrop(self, file_path: str) -> None:
        """Called after Qt releases clipboard; sets CF_HDROP silently."""
        ok = self._set_cf_hdrop(file_path)
        _log.info("deferred CF_HDROP set: %s for %s", ok, file_path)

    def _add_entry(self, entry: ClipboardEntry) -> None:
        self.history.insert(0, entry)
        if len(self.history) > self.max_history:
            self.history = self.history[:self.max_history]
        self.history_changed.emit()

    def _restore_own_copy(self) -> None:
        own = self._own_copy
        if own is None:
            return
        clipboard = QApplication.clipboard()
        mime = QMimeData()
        if own["kind"] == "image_with_path":
            mime.setImageData(own["image"])
        mime.setText(own["path"])
        mime.setUrls([QUrl.fromLocalFile(own["path"])])
        self._suppress_count += 1
        clipboard.setMimeData(mime)
        self._last_text = own["path"]
        _log.info("accidental selection replaced the capture; restored %s", own["path"])

    def _maybe_restore_after_accident(self, mime: QMimeData) -> bool:
        """Undo a border/empty selection that landed right after our capture."""
        own = self._own_copy
        if own is None:
            return False
        if time.time() - float(own["at"]) > _RESTORE_WINDOW_SEC:
            self._own_copy = None
            return False
        if mime.hasImage() or mime.hasUrls():
            return False
        text = mime.text() if mime.hasText() else ""
        if text == own["path"] or not is_accidental_selection(text):
            return False
        if not Path(own["path"]).exists():
            self._own_copy = None
            return False
        _log.info("clipboard became an accidental selection %r after a capture", text[:20])
        QTimer.singleShot(0, self._restore_own_copy)
        return True

    def _on_clipboard_changed(self) -> None:
        """Called by Qt's clipboard.dataChanged signal (instant, no polling)."""
        if self._suppress_count > 0:
            self._suppress_count -= 1
            _log.debug("clipboard change suppressed (count was %d)", self._suppress_count + 1)
            return

        try:
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime is None:
                return

            if self._maybe_restore_after_accident(mime):
                return
            # Anything else the user copies on purpose ends the restore window.
            if self._own_copy is not None:
                current = mime.text() if mime.hasText() else ""
                if current != self._own_copy["path"]:
                    self._own_copy = None

            # Check text FIRST - avoids misclassifying rich-text copies as images
            if mime.hasText():
                text = clipboard.text()
                _log.debug("clipboard text: %s (last: %s)", text[:80] if text else "", self._last_text[:80] if self._last_text else "")
                if text and text != self._last_text:
                    # Auto-enrich file:/// URLs with CF_HDROP for Explorer paste
                    if self._try_enrich_file_url(text):
                        return
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
