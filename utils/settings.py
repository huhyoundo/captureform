from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "start_with_windows": False,
        "minimize_to_tray": True,
        "language": "ko",
        "theme": "dark",
        "sound_effects": True,
        "capture_notification": True,
    },
    "capture": {
        "default_action": "copy",
        "show_cursor": False,
        "include_shadow": True,
        "auto_save": True,
        "save_directory": "~/Pictures/SuperCapture/",
        "filename_pattern": "SC_{date}_{time}_{index}",
        "image_format": "png",
        "jpg_quality": 95,
        "record_fps": 24,
        "region_border_color": "#00AAFF",
        "magnifier_zoom": 4,
        "smart_edge_snap": True,
        "multi_monitor": "all",
    },
    "ocr": {
        "api_key": "",
        "api_key_encrypted": False,
        "model": "gpt-4o",
        "auto_language_detect": True,
        "default_language": "ko",
        "preserve_formatting": True,
        "auto_copy_result": True,
    },
    "clipboard": {
        "max_history": 50,
        "auto_clear_hours": 24,
        "save_ocr_text": True,
    },
    "hotkeys": {
        "region_capture": "ctrl+shift+c",
        "repeat_capture": "ctrl+shift+r",
        "clipboard_history": "ctrl+alt+v",
        "region_capture_suppress": False,
        "repeat_capture_suppress": False,
        "trigger_on_release": True,
        "debounce_ms": 280,
    },
    "editor": {
        "default_pen_color": "#FF0000",
        "default_pen_width": 3,
        "default_highlight_color": "#FFFF00",
        "auto_number_start": 1,
        "mosaic_pixel_size": 10,
    },
}


class SettingsManager:
    def __init__(self, config_path: str | Path = "config.json") -> None:
        self.config_path = Path(config_path)
        self.secret_dir = Path.home() / ".supercapture"
        self.secret_dir.mkdir(parents=True, exist_ok=True)
        self.key_path = self.secret_dir / "fernet.key"
        self.config: dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self) -> dict[str, Any]:
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.config = self._deep_merge(deepcopy(DEFAULT_CONFIG), loaded)
            except (json.JSONDecodeError, OSError):
                self.config = deepcopy(DEFAULT_CONFIG)
        else:
            self.config = deepcopy(DEFAULT_CONFIG)
            self.save()

        api_key = self.config["ocr"].get("api_key", "")
        encrypted = bool(self.config["ocr"].get("api_key_encrypted", False))
        if api_key and not encrypted:
            self.set_openai_api_key(api_key)

        return self.config

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def get(self, *keys: str, default: Any = None) -> Any:
        cur: Any = self.config
        for key in keys:
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur

    def set(self, value: Any, *keys: str) -> None:
        if not keys:
            raise ValueError("At least one key must be provided")
        cur: dict[str, Any] = self.config
        for key in keys[:-1]:
            if key not in cur or not isinstance(cur[key], dict):
                cur[key] = {}
            cur = cur[key]
        cur[keys[-1]] = value
        self.save()

    def set_openai_api_key(self, api_key: str) -> None:
        if not api_key:
            self.config["ocr"]["api_key"] = ""
            self.config["ocr"]["api_key_encrypted"] = False
            self.save()
            return

        token = self._get_fernet().encrypt(api_key.encode("utf-8")).decode("utf-8")
        self.config["ocr"]["api_key"] = token
        self.config["ocr"]["api_key_encrypted"] = True
        self.save()

    def get_openai_api_key(self) -> str:
        token = self.config["ocr"].get("api_key", "")
        if not token:
            return ""
        if not self.config["ocr"].get("api_key_encrypted", False):
            return str(token)

        try:
            return self._get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            return ""

    def _get_fernet(self) -> Fernet:
        if not self.key_path.exists():
            key = Fernet.generate_key()
            self.key_path.write_bytes(key)
        key_bytes = self.key_path.read_bytes()
        return Fernet(key_bytes)

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        for key, value in override.items():
            if (
                key in base
                and isinstance(base[key], dict)
                and isinstance(value, dict)
            ):
                base[key] = SettingsManager._deep_merge(base[key], value)
            else:
                base[key] = value
        return base
