from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtGui import QImage

from utils.settings import SettingsManager


class FileManager:
    def __init__(self, settings: SettingsManager) -> None:
        self.settings = settings
        self._index = 1

    def get_save_directory(self) -> Path:
        configured = self.settings.get("capture", "save_directory", default="~/Pictures/SuperCapture/")
        path = Path(os.path.expanduser(str(configured))).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_capture(self, image: QImage) -> Path:
        save_dir = self.get_save_directory()
        fmt = str(self.settings.get("capture", "image_format", default="png")).lower()
        if fmt not in {"png", "jpg", "jpeg", "webp", "bmp"}:
            fmt = "png"

        ext = "jpg" if fmt == "jpeg" else fmt
        file_path = save_dir / self._generate_name(ext)

        quality = int(self.settings.get("capture", "jpg_quality", default=95))
        if ext == "jpg":
            image.save(str(file_path), "JPG", quality)
        else:
            image.save(str(file_path), ext.upper())

        self._index += 1
        return file_path

    def create_recording_path(self, extension: str = "gif") -> Path:
        save_dir = self.get_save_directory()
        ext = extension.lower().lstrip(".") or "gif"
        now = datetime.now()
        base_name = f"SC_{now:%Y%m%d_%H%M%S}_record"
        candidate = save_dir / f"{base_name}.{ext}"

        suffix = 1
        while candidate.exists():
            candidate = save_dir / f"{base_name}_{suffix:02d}.{ext}"
            suffix += 1

        return candidate

    def _generate_name(self, extension: str) -> str:
        now = datetime.now()
        return f"SC_{now:%Y%m%d_%H%M%S}_{self._index:03d}.{extension}"
