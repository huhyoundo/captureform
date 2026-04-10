"""File drop helper: opens Explorer with file selected for easy drag to any app."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

from PyQt6.QtWidgets import QApplication

_log = logging.getLogger(__name__)


def get_file_from_clipboard() -> str | None:
    """Check clipboard for a file:/// URL and return the local path, or None."""
    try:
        cb = QApplication.clipboard()
        mime = cb.mimeData()
        if mime and mime.hasText():
            text = cb.text().strip()
            if text.startswith("file:///"):
                parsed = urlparse(text)
                local_path = unquote(parsed.path)
                if len(local_path) >= 3 and local_path[0] == "/" and local_path[2] == ":":
                    local_path = local_path[1:]
                path = Path(local_path)
                if path.exists():
                    return str(path)
    except Exception:
        pass

    # Also check CF_HDROP
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            files = win32clipboard.GetClipboardData(win32clipboard.CF_HDROP)
            if files:
                return files[0]
        except Exception:
            pass
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass

    return None


def open_file_in_explorer(file_path: str) -> None:
    """Open Explorer with the file selected - ready to drag to any app."""
    path = file_path.replace("/", "\\")
    subprocess.Popen(f'explorer /select,"{path}"')
    _log.info("Opened Explorer with file selected: %s", path)
