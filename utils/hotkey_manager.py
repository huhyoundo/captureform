from __future__ import annotations

import ctypes
import os
import sys
import time
from collections import Counter
from ctypes import wintypes
from typing import Any

from PyQt6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, pyqtSignal


WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

user32 = ctypes.WinDLL("user32", use_last_error=True)


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class _WindowsHotkeyEventFilter(QAbstractNativeEventFilter):
    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        try:
            if isinstance(event_type, (bytes, bytearray)):
                event_name = bytes(event_type).decode(errors="ignore")
            else:
                try:
                    event_name = bytes(event_type).decode(errors="ignore")
                except Exception:
                    event_name = str(event_type)
            if event_name not in ("windows_generic_MSG", "windows_dispatcher_MSG"):
                return False, 0
            msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
            if int(msg.message) != WM_HOTKEY:
                return False, 0
            self._callback(int(msg.wParam))
            return True, 0
        except Exception:
            return False, 0


class HotkeyManager(QObject):
    hotkey_pressed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._id_to_action: dict[int, str] = {}
        self._debounce_ms_by_action: dict[str, int] = {}
        self._last_trigger_by_action: dict[str, float] = {}
        self._next_hotkey_id = 1
        self._event_filter: _WindowsHotkeyEventFilter | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_hotkeys(self, mapping: dict[str, str | dict[str, Any]]) -> None:
        if os.name != "nt":
            raise RuntimeError("Global hotkeys are supported only on Windows.")

        self.unregister_all()
        self._patch_stdio()
        self._install_event_filter()

        normalized = self._normalize_mapping(mapping)
        self._validate_conflicts(normalized)

        failed: list[str] = []
        for action, hotkey in normalized.items():
            combo = hotkey["combo"]
            if not combo:
                continue

            modifiers, vk = self._parse_combo(combo)
            hotkey_id = self._next_id()

            ok = user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk)
            if not ok:
                code = ctypes.get_last_error()
                failed.append(f"'{combo}' (code={code})")
                continue

            self._id_to_action[hotkey_id] = action
            self._debounce_ms_by_action[action] = int(hotkey["debounce_ms"])

        if failed and not self._id_to_action:
            raise RuntimeError(f"RegisterHotKey failed for all: {', '.join(failed)}")
        if failed:
            import logging
            logging.getLogger(__name__).warning(
                "Some hotkeys failed to register: %s", ", ".join(failed)
            )

    def unregister_all(self) -> None:
        if os.name != "nt":
            return

        for hotkey_id in list(self._id_to_action.keys()):
            try:
                user32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                pass

        self._id_to_action.clear()
        self._debounce_ms_by_action.clear()
        self._last_trigger_by_action.clear()
        self._remove_event_filter()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _patch_stdio() -> None:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")

    @staticmethod
    def _validate_conflicts(mapping: dict[str, dict[str, Any]]) -> None:
        combos = [str(entry["combo"]).lower().strip() for entry in mapping.values() if entry["combo"]]
        duplicated = [combo for combo, count in Counter(combos).items() if count > 1]
        if duplicated:
            dup = ", ".join(duplicated)
            raise ValueError(f"Hotkey conflict detected: {dup}")

    @staticmethod
    def _normalize_mapping(mapping: dict[str, str | dict[str, Any]]) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for action, value in mapping.items():
            if isinstance(value, dict):
                combo = str(value.get("combo", "")).strip()
                try:
                    debounce_ms = int(value.get("debounce_ms", 280))
                except (TypeError, ValueError):
                    debounce_ms = 280
            else:
                combo = str(value).strip()
                debounce_ms = 280
            normalized[action] = {
                "combo": combo,
                "debounce_ms": max(0, debounce_ms),
            }
        return normalized

    def _install_event_filter(self) -> None:
        app = QCoreApplication.instance()
        if app is None:
            raise RuntimeError("QCoreApplication is not initialized.")
        if self._event_filter is None:
            self._event_filter = _WindowsHotkeyEventFilter(self._on_hotkey_message)
            app.installNativeEventFilter(self._event_filter)

    def _remove_event_filter(self) -> None:
        app = QCoreApplication.instance()
        if app is None:
            return
        if self._event_filter is not None:
            app.removeNativeEventFilter(self._event_filter)
            self._event_filter = None

    def _on_hotkey_message(self, hotkey_id: int) -> None:
        action_name = self._id_to_action.get(hotkey_id)
        if not action_name:
            return

        debounce_ms = int(self._debounce_ms_by_action.get(action_name, 280))
        now = time.monotonic()
        last = self._last_trigger_by_action.get(action_name, 0.0)
        if debounce_ms > 0 and (now - last) * 1000.0 < debounce_ms:
            return

        self._last_trigger_by_action[action_name] = now
        self.hotkey_pressed.emit(action_name)

    def _next_id(self) -> int:
        hotkey_id = self._next_hotkey_id
        self._next_hotkey_id += 1

        if self._next_hotkey_id > 0xBFFF:
            self._next_hotkey_id = 1

        while hotkey_id in self._id_to_action:
            hotkey_id = self._next_hotkey_id
            self._next_hotkey_id += 1
            if self._next_hotkey_id > 0xBFFF:
                self._next_hotkey_id = 1

        return hotkey_id

    @staticmethod
    def _parse_combo(combo: str) -> tuple[int, int]:
        if not combo:
            raise ValueError("Empty hotkey combo.")

        tokens = [token.strip().lower() for token in combo.split("+") if token.strip()]
        if not tokens:
            raise ValueError("Invalid hotkey combo.")

        modifier_map = {
            "alt": MOD_ALT,
            "ctrl": MOD_CONTROL,
            "control": MOD_CONTROL,
            "shift": MOD_SHIFT,
            "win": MOD_WIN,
            "windows": MOD_WIN,
            "cmd": MOD_WIN,
            "meta": MOD_WIN,
        }

        vk_map = {
            "esc": 0x1B,
            "escape": 0x1B,
            "tab": 0x09,
            "enter": 0x0D,
            "return": 0x0D,
            "space": 0x20,
            "backspace": 0x08,
            "delete": 0x2E,
            "del": 0x2E,
            "insert": 0x2D,
            "ins": 0x2D,
            "home": 0x24,
            "end": 0x23,
            "pageup": 0x21,
            "pgup": 0x21,
            "pagedown": 0x22,
            "pgdn": 0x22,
            "up": 0x26,
            "down": 0x28,
            "left": 0x25,
            "right": 0x27,
        }

        modifiers = 0
        vk: int | None = None

        for token in tokens:
            modifier = modifier_map.get(token)
            if modifier is not None:
                modifiers |= modifier
                continue

            if vk is not None:
                raise ValueError(f"Hotkey must contain exactly one main key: {combo}")

            if len(token) == 1 and token.isalpha():
                vk = ord(token.upper())
                continue

            if len(token) == 1 and token.isdigit():
                vk = ord(token)
                continue

            if token.startswith("f") and token[1:].isdigit():
                number = int(token[1:])
                if 1 <= number <= 24:
                    vk = 0x70 + (number - 1)
                    continue

            named_vk = vk_map.get(token)
            if named_vk is not None:
                vk = named_vk
                continue

            raise ValueError(f"Unsupported hotkey key: '{token}'")

        if modifiers == 0:
            raise ValueError(f"Hotkey requires at least one modifier key: {combo}")
        if vk is None:
            raise ValueError(f"Hotkey requires a main key: {combo}")

        return modifiers, vk
