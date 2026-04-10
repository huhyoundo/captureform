from __future__ import annotations

import logging
import os
import subprocess
import shutil
import sys
from pathlib import Path

logging.basicConfig(
    filename=os.path.join(os.path.expanduser("~"), "callcap_debug.log"),
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

if getattr(sys, "frozen", False):
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot, QRect, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QSystemTrayIcon,
)

from capture.region_recorder import RegionRecordingSession
from capture.region_selector import CaptureActionToolbar, RegionSelector
from capture.repeat_capture import RepeatCapture, RepeatDiffResult
from capture.screen_capture import ScreenCaptureService
from clipboard.clipboard_manager import ClipboardManager
from clipboard.file_drop_popup import get_file_from_clipboard, open_file_in_explorer
from clipboard.pin_window import PinWindow
from ocr.ocr_dialog import OCRResultDialog
from ocr.ocr_engine import OCREngine
from ui.diff_dialog import RepeatDiffDialog
from ui.history_panel import ClipboardHistoryWindow
from ui.tray_menu import TrayMenuController
from ads.ad_manager import AdManager
from ads.ad_popup import AdPopupWindow
from utils.auto_updater import AutoUpdater, CURRENT_VERSION
from utils.update_dialog import UpdateDialog
from utils.file_manager import FileManager
from utils.hotkey_manager import HotkeyManager
from utils.settings import SettingsManager
from utils.startup import is_startup_enabled, set_startup


class OCRWorker(QObject):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, engine: OCREngine, image_bytes: bytes) -> None:
        super().__init__()
        self._engine = engine
        self._image_bytes = image_bytes

    @pyqtSlot()
    def run(self) -> None:
        try:
            text = self._engine.extract_text(self._image_bytes, options={"preserve_formatting": True})
            self.finished.emit(text)
        except Exception as exc:  # pragma: no cover - runtime/network error path
            self.failed.emit(str(exc))


class CallcapController(QObject):
    request_region_capture = pyqtSignal()
    request_repeat_capture = pyqtSignal()

    def __init__(self, app: QApplication, config_path: str | Path = "config.json") -> None:
        super().__init__()
        self.app = app

        self.settings = SettingsManager(config_path)
        self.file_manager = FileManager(self.settings)
        self.capture_service = ScreenCaptureService()

        max_history = int(self.settings.get("clipboard", "max_history", default=50))
        self.clipboard = ClipboardManager(max_history=max_history)
        self._file_drop_popup = None  # kept for compat
        self.ocr_engine = OCREngine(self.settings)
        self.repeat_capture = RepeatCapture()

        self.region_hotkey = str(self.settings.get("hotkeys", "region_capture", default="ctrl+shift+c"))
        self.repeat_hotkey = str(self.settings.get("hotkeys", "repeat_capture", default="ctrl+shift+r"))
        self.clipboard_hotkey = str(self.settings.get("hotkeys", "clipboard_history", default="ctrl+alt+v"))
        self.file_drop_hotkey = str(self.settings.get("hotkeys", "file_drop", default="ctrl+shift+x"))

        startup_enabled = is_startup_enabled()
        if bool(self.settings.get("general", "start_with_windows", default=False)) != startup_enabled:
            self.settings.set(startup_enabled, "general", "start_with_windows")

        self.tray = TrayMenuController(
            "Callcap",
            region_hotkey=self.region_hotkey,
            repeat_hotkey=self.repeat_hotkey,
            clipboard_hotkey=self.clipboard_hotkey,
            startup_enabled=startup_enabled,
        )
        self.hotkeys = HotkeyManager()

        self.clipboard_history_window: ClipboardHistoryWindow | None = None

        self.selector: RegionSelector | None = None
        self.toolbar: CaptureActionToolbar | None = None
        self.region_recorder: RegionRecordingSession | None = None

        self.current_image: QImage | None = None
        self.current_region = None
        self.current_saved_path: Path | None = None
        self.editor_windows: list[object] = []
        self.pin_windows: list[PinWindow] = []

        self._ocr_thread: QThread | None = None
        self._ocr_worker: OCRWorker | None = None
        self._ocr_progress: QProgressDialog | None = None
        self._mp4_progress: QProgressDialog | None = None

        # Ad system
        self._ad_manager = AdManager()
        self._ad_popup: AdPopupWindow | None = None
        self._capture_count = 0

        # Auto-update
        self._updater = AutoUpdater()
        self._updater.update_available.connect(self._on_update_available)

        self._setup_signals()
        self._setup_hotkeys()
        self.tray.show()
        self.tray.show_message(
            "Callcap",
            f"앱이 백그라운드에서 실행 중입니다.\n{self._display_hotkey(self.region_hotkey)} 를 눌러 화면 캡처를 시작하세요.",
        )

        # Delayed startup tasks: ad popup (3s) and update check (5s)
        QTimer.singleShot(3000, self._show_startup_ad)
        QTimer.singleShot(5000, self._updater.check_for_updates)

    @staticmethod
    def _display_hotkey(raw: str) -> str:
        cleaned = str(raw).replace(" ", "").upper()
        return cleaned.replace("+", " + ")

    def _setup_signals(self) -> None:
        self.request_region_capture.connect(self.start_region_capture)
        self.request_repeat_capture.connect(self.start_repeat_capture)
        self.tray.region_capture_requested.connect(self.start_region_capture)
        self.tray.repeat_capture_requested.connect(self.start_repeat_capture)
        self.tray.open_save_folder_requested.connect(self.open_save_folder)
        self.tray.clipboard_history_requested.connect(self.toggle_clipboard_history)
        self.tray.startup_toggled.connect(self._on_startup_toggled)
        self.tray.quit_requested.connect(self.shutdown)
        self.hotkeys.hotkey_pressed.connect(self._on_hotkey_pressed)

    def _reset_toolbar(self) -> None:
        if self.toolbar is None:
            return
        try:
            self.toolbar.close()
            self.toolbar.deleteLater()
        finally:
            self.toolbar = None

    def _setup_hotkeys(self) -> None:
        region_hotkey = self.region_hotkey
        repeat_hotkey = self.repeat_hotkey
        configured_region_suppress = bool(
            self.settings.get("hotkeys", "region_capture_suppress", default=False)
        )
        configured_repeat_suppress = bool(
            self.settings.get("hotkeys", "repeat_capture_suppress", default=False)
        )
        if configured_region_suppress:
            self.settings.set(False, "hotkeys", "region_capture_suppress")
        if configured_repeat_suppress:
            self.settings.set(False, "hotkeys", "repeat_capture_suppress")
        suppress_region_shortcut = False
        suppress_repeat_shortcut = False
        trigger_on_release = bool(
            self.settings.get("hotkeys", "trigger_on_release", default=True)
        )
        debounce_raw = self.settings.get("hotkeys", "debounce_ms", default=280)
        try:
            debounce_ms = int(debounce_raw)
        except (TypeError, ValueError):
            debounce_ms = 280

        clipboard_hotkey = self.clipboard_hotkey

        mapping = {
            "region_capture": {
                "combo": region_hotkey,
                "suppress": suppress_region_shortcut,
                "trigger_on_release": trigger_on_release,
                "debounce_ms": debounce_ms,
            },
            "repeat_capture": {
                "combo": repeat_hotkey,
                "suppress": suppress_repeat_shortcut,
                "trigger_on_release": trigger_on_release,
                "debounce_ms": debounce_ms,
            },
            "clipboard_history": {
                "combo": clipboard_hotkey,
                "suppress": False,
                "trigger_on_release": trigger_on_release,
                "debounce_ms": debounce_ms,
            },
            "file_drop": {
                "combo": self.file_drop_hotkey,
                "suppress": False,
                "trigger_on_release": False,
                "debounce_ms": 200,
            },
        }

        try:
            self.hotkeys.register_hotkeys(mapping)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Hotkey registration failed: %s", e)
            self.tray.show_message(
                "Callcap",
                f"단축키 등록에 실패했습니다: {e}\n트레이 메뉴를 사용하세요.",
            )

    def _show_file_drop_popup(self) -> None:
        file_path = get_file_from_clipboard()
        if not file_path:
            return
        open_file_in_explorer(file_path)

    @pyqtSlot(str)
    def _on_hotkey_pressed(self, action: str) -> None:
        if action == "region_capture":
            self.request_region_capture.emit()
            return
        if action == "repeat_capture":
            self.request_repeat_capture.emit()
            return
        if action == "clipboard_history":
            self.toggle_clipboard_history()
            return
        if action == "file_drop":
            self._show_file_drop_popup()
            return

    @pyqtSlot()
    def start_region_capture(self) -> None:
        if self._is_recording():
            self.tray.show_message("Callcap", "Recording is in progress. Click Stop first.")
            return
        if self._is_saving_mp4():
            self.tray.show_message("Callcap", "MP4 is being saved. Please wait.")
            return
        if self.selector is not None:
            return

        self._cleanup_recorder()
        self._reset_toolbar()

        border_color = str(self.settings.get("capture", "region_border_color", default="#00AAFF"))
        self.selector = RegionSelector(border_color=border_color)
        self.selector.region_selected.connect(self._on_region_selected)
        self.selector.cancelled.connect(self._on_region_cancelled)
        self.selector.start()

    @pyqtSlot()
    def start_repeat_capture(self) -> None:
        if self._is_recording():
            self.tray.show_message("Callcap", "Recording is in progress. Click Stop first.")
            return
        if self._is_saving_mp4():
            self.tray.show_message("Callcap", "MP4 is being saved. Please wait.")
            return
        if self.selector is not None:
            return
        self._cleanup_recorder()
        self._reset_toolbar()

        last_region = self.repeat_capture.get_last_region()
        if last_region is None:
            self.tray.show_message("Callcap", "No previous capture region found.")
            return
        QTimer.singleShot(50, lambda: self._capture_and_show_toolbar(last_region, source="repeat"))

    @pyqtSlot()
    def _on_region_cancelled(self) -> None:
        self.selector = None

    @pyqtSlot(QRect)
    def _on_region_selected(self, rect: QRect) -> None:
        self.selector = None
        QTimer.singleShot(150, lambda: self._capture_and_show_toolbar(rect, source="region"))

    def _capture_and_show_toolbar(self, rect, source: str = "region") -> None:
        try:
            image = self.capture_service.capture_region(rect)
        except Exception as exc:
            self._warn("Capture failed", f"Could not capture selected region.\n{exc}")
            return

        diff_result = None
        if source == "repeat":
            diff_result = self.repeat_capture.compare_with_last(image)

        self.current_image = image
        self.current_region = rect

        # Save first so we have the file path for clipboard
        self.current_saved_path = self.file_manager.save_capture(image)
        self.repeat_capture.set_last_capture(rect, image)

        # Ad after every Nth capture
        self._capture_count += 1
        if self._ad_manager.should_show_ad_for_capture(self._capture_count):
            QTimer.singleShot(1500, self._show_capture_ad)

        # Copy image + file path to clipboard: terminals paste the path, image apps paste the image
        copy_path_enabled = bool(
            self.settings.get("capture", "copy_path_with_image", default=True)
        )
        if copy_path_enabled and self.current_saved_path is not None:
            self.clipboard.copy_image_with_path(image, self.current_saved_path)
        else:
            self.clipboard.copy_image(image)

        if source == "repeat":
            changed_ratio = 0.0 if diff_result is None else diff_result.changed_ratio * 100.0
            self.tray.show_message(
                "Callcap",
                f"Repeat captured {rect.width()}x{rect.height()} | Changed: {changed_ratio:.2f}%",
            )
        else:
            if copy_path_enabled and self.current_saved_path is not None:
                self.tray.show_message(
                    "Callcap",
                    f"Captured {rect.width()}x{rect.height()} — image + path copied.\n{self.current_saved_path}",
                )
            else:
                self.tray.show_message(
                    "Callcap",
                    f"Captured {rect.width()}x{rect.height()} and copied to clipboard.",
                )

        self._reset_toolbar()
        self.toolbar = CaptureActionToolbar()
        self.toolbar.action_selected.connect(self._handle_toolbar_action)
        self.toolbar.set_recording(False)
        self.toolbar.set_record_busy(False)
        self.toolbar.show_near(rect)

        if source == "repeat" and diff_result is not None:
            self._show_repeat_diff(diff_result)

    @pyqtSlot(str)
    def _handle_toolbar_action(self, action: str) -> None:
        if action == "record":
            if self._is_recording():
                self.stop_recording()
            else:
                self.start_recording()
            return

        if action == "mp4":
            self.save_recording_as_mp4()
            return

        if action == "copy":
            if self.current_image is not None:
                copy_path_enabled = bool(
                    self.settings.get("capture", "copy_path_with_image", default=True)
                )
                if copy_path_enabled and self.current_saved_path is not None:
                    self.clipboard.copy_image_with_path(self.current_image, self.current_saved_path)
                    self.tray.show_message("Callcap", "Image + path copied to clipboard.")
                else:
                    self.clipboard.copy_image(self.current_image)
                    self.tray.show_message("Callcap", "Image copied to clipboard.")
            return

        if action == "pin":
            self.pin_current_image()
            return

        if action == "ocr":
            self.run_ocr()
            return

        if action == "edit":
            self.open_editor()
            return

        if action == "save":
            self.save_as()
            return

        if action == "folder":
            self.open_save_folder()
            return

        if action == "cancel":
            if self._is_recording():
                self.stop_recording()
                return
            if self._is_saving_mp4():
                self.tray.show_message("Callcap", "MP4 is being saved. Please wait.")
                return
            self._cleanup_recorder()
            self._reset_toolbar()

    def save_as(self) -> None:
        if self.current_image is None:
            return

        default_path = self.current_saved_path or (self.file_manager.get_save_directory() / "capture.png")
        filename, _ = QFileDialog.getSaveFileName(
            None,
            "Save Capture As",
            str(default_path),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not filename:
            return
        self.current_image.save(filename)
        self.tray.show_message("Callcap", f"Saved: {filename}")

    def start_recording(self) -> None:
        if self.current_region is None:
            self._warn("Recording", "No selected region to record.")
            return
        if self._is_recording():
            return

        fps_raw = self.settings.get("capture", "record_fps", default=24)
        try:
            fps = int(fps_raw)
        except (TypeError, ValueError):
            fps = 24
        fps = max(8, min(60, fps))

        output_path = self.file_manager.create_recording_path("gif")
        recorder = RegionRecordingSession(
            capture_service=self.capture_service,
            rect=QRect(self.current_region),
            output_path=output_path,
            fps=fps,
        )
        recorder.finished.connect(self._on_recording_finished)
        recorder.failed.connect(self._on_recording_failed)
        recorder.mp4_finished.connect(self._on_mp4_finished)
        recorder.mp4_failed.connect(self._on_mp4_failed)
        self.region_recorder = recorder
        recorder.start()

        if not recorder.is_running:
            return

        if self.toolbar is not None:
            self.toolbar.set_recording(True)
            self.toolbar.set_record_busy(False)

        self.tray.show_message(
            "Callcap",
            "Recording started. Click Stop in the toolbar when done.",
        )

    def stop_recording(self) -> None:
        if not self._is_recording():
            return

        if self.toolbar is not None:
            self.toolbar.set_record_busy(True)

        self.tray.show_message("Callcap", "Stopping recording and saving GIF...")
        if self.region_recorder is not None:
            self.region_recorder.stop()

    def run_ocr(self) -> None:
        if self.current_image is None:
            return

        if not self._ensure_api_key():
            return

        image_bytes = ScreenCaptureService.image_to_png_bytes(self.current_image)

        self._ocr_progress = QProgressDialog("텍스트 추출 중...", None, 0, 0)
        self._ocr_progress.setWindowTitle("Callcap OCR")
        self._ocr_progress.setCancelButton(None)
        self._ocr_progress.setMinimumDuration(0)
        self._ocr_progress.setAutoClose(False)
        self._ocr_progress.setAutoReset(False)
        self._ocr_progress.show()

        self._ocr_worker = OCRWorker(self.ocr_engine, image_bytes)
        self._ocr_thread = QThread(self)
        self._ocr_worker.moveToThread(self._ocr_thread)

        self._ocr_thread.started.connect(self._ocr_worker.run)
        self._ocr_worker.finished.connect(self._on_ocr_finished)
        self._ocr_worker.failed.connect(self._on_ocr_failed)
        self._ocr_worker.finished.connect(self._cleanup_ocr_thread)
        self._ocr_worker.failed.connect(self._cleanup_ocr_thread)
        self._ocr_thread.start()

    def _ensure_api_key(self) -> bool:
        if self.ocr_engine.is_configured():
            return True

        key, ok = QInputDialog.getText(
            None,
            "OpenAI API Key",
            "Enter OpenAI API key for OCR:",
            QLineEdit.EchoMode.Password,
        )
        key = key.strip()
        if not ok or not key:
            return False

        self.settings.set_openai_api_key(key)
        return True

    @pyqtSlot(str)
    def _on_ocr_finished(self, text: str) -> None:
        if self._ocr_progress is not None:
            self._ocr_progress.close()
            self._ocr_progress = None

        if self.settings.get("ocr", "auto_copy_result", default=True):
            self.clipboard.copy_text(text)

        dialog = OCRResultDialog(text, clipboard=self.clipboard)
        dialog.exec()

    @pyqtSlot(str)
    def _on_ocr_failed(self, error: str) -> None:
        if self._ocr_progress is not None:
            self._ocr_progress.close()
            self._ocr_progress = None
        self._warn("OCR failed", error)

    def _cleanup_ocr_thread(self) -> None:
        if self._ocr_thread is None:
            return
        self._ocr_thread.quit()
        self._ocr_thread.wait(1000)
        self._ocr_thread = None
        self._ocr_worker = None

    def _show_mp4_progress(self) -> None:
        if self._mp4_progress is not None:
            self._mp4_progress.close()
            self._mp4_progress = None
        self._mp4_progress = QProgressDialog("MP4로 저장 중입니다...", None, 0, 0)
        self._mp4_progress.setWindowTitle("Callcap MP4")
        self._mp4_progress.setCancelButton(None)
        self._mp4_progress.setMinimumDuration(0)
        self._mp4_progress.setAutoClose(False)
        self._mp4_progress.setAutoReset(False)
        self._mp4_progress.show()

    def _hide_mp4_progress(self) -> None:
        if self._mp4_progress is not None:
            self._mp4_progress.close()
            self._mp4_progress = None

    @pyqtSlot(str, int, float)
    def _on_recording_finished(self, output_path: str, frame_count: int, elapsed: float) -> None:
        path = Path(output_path)
        self.current_saved_path = path

        if self.toolbar is not None:
            self.toolbar.set_recording(False)
            self.toolbar.set_record_busy(False)
            self.toolbar.show_mp4_button(True)

        self.tray.show_message(
            "Callcap",
            f"Recording saved: {path.name} ({elapsed:.1f}s, {frame_count} frames)",
        )

    @pyqtSlot(str)
    def _on_recording_failed(self, error: str) -> None:
        if self.toolbar is not None:
            self.toolbar.set_recording(False)
            self.toolbar.set_record_busy(False)

        self._cleanup_recorder()
        self._warn("Recording failed", error)

    def save_recording_as_mp4(self) -> None:
        if self.region_recorder is None or not self.region_recorder.has_frames:
            self.tray.show_message("Callcap", "No recorded frames available for MP4.")
            return
        if self.region_recorder.is_saving_mp4:
            self.tray.show_message("Callcap", "MP4 is already being saved.")
            return

        mp4_path = self.file_manager.create_recording_path("mp4")

        if self.toolbar is not None:
            mp4_btn = self.toolbar._buttons.get("mp4")
            if mp4_btn is not None:
                mp4_btn.setEnabled(False)
                mp4_btn.setText("Saving...")
            self.toolbar.set_record_busy(True)

        self._show_mp4_progress()
        self.tray.show_message("Callcap", "Saving MP4...")
        self.region_recorder.save_as_mp4(mp4_path)

    @pyqtSlot(str)
    def _on_mp4_finished(self, output_path: str) -> None:
        path = Path(output_path)
        self._hide_mp4_progress()
        self.tray.show_message(
            "Callcap",
            f"MP4로 저장되었습니다: {path.name}\n클릭하면 파일 위치를 엽니다.",
            on_click=lambda p=path: self._reveal_file_in_explorer(p),
            duration_ms=6000,
        )

        if self.toolbar is not None:
            mp4_btn = self.toolbar._buttons.get("mp4")
            if mp4_btn is not None:
                mp4_btn.setEnabled(True)
                mp4_btn.setText("MP4")
            self.toolbar.set_record_busy(False)

    @pyqtSlot(str)
    def _on_mp4_failed(self, error: str) -> None:
        self._hide_mp4_progress()
        self.tray.show_message("Callcap", f"MP4 save failed: {error}")

        if self.toolbar is not None:
            mp4_btn = self.toolbar._buttons.get("mp4")
            if mp4_btn is not None:
                mp4_btn.setEnabled(True)
                mp4_btn.setText("MP4")
            self.toolbar.set_record_busy(False)

    def _cleanup_recorder(self) -> None:
        if self.region_recorder is not None:
            if self.region_recorder.is_saving_mp4:
                return
            self.region_recorder.cleanup()
            self.region_recorder.deleteLater()
            self.region_recorder = None

    def open_save_folder(self) -> None:
        folder = self.file_manager.get_save_directory()
        os.startfile(str(folder))

    def _reveal_file_in_explorer(self, file_path: Path) -> None:
        target = file_path.expanduser()
        if not target.exists():
            parent = target.parent
            if parent.exists():
                os.startfile(str(parent))
            return

        if os.name == "nt":
            try:
                subprocess.Popen(["explorer", f"/select,{target}"])
                return
            except Exception:
                pass

        os.startfile(str(target.parent))

    def _warn(self, title: str, message: str) -> None:
        QMessageBox.warning(None, title, message)

    def pin_current_image(self) -> None:
        if self.current_image is None:
            return
        from PyQt6.QtGui import QPixmap

        pixmap = QPixmap.fromImage(self.current_image)
        pin = PinWindow(pixmap, file_path=self.current_saved_path)
        pin.closed.connect(self._on_pin_closed)
        self.pin_windows.append(pin)

        # Show near center of the captured region
        if self.current_region is not None:
            x = self.current_region.center().x() - pin.width() // 2
            y = self.current_region.center().y() - pin.height() // 2
            pin.move(x, y)

        pin.show()
        self._reset_toolbar()

    def _on_pin_closed(self, pin: PinWindow) -> None:
        if pin in self.pin_windows:
            self.pin_windows.remove(pin)

    def open_editor(self) -> None:
        if self.current_image is None:
            self._warn("Edit", "No captured image to edit.")
            return

        try:
            from capture_editor.editor_window import EditorWindow
        except Exception as exc:
            self._warn("Edit", f"Failed to open editor.\n{exc}")
            return

        try:
            editor = EditorWindow(image=self.current_image.copy())
            editor.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            editor.destroyed.connect(lambda _obj=None, w=editor: self._on_editor_closed(w))
            self.editor_windows.append(editor)
            editor.show()
            editor.raise_()
            editor.activateWindow()
        except Exception as exc:
            self._warn("Edit", f"Failed to initialize editor.\n{exc}")

    def _on_editor_closed(self, editor: object) -> None:
        if editor in self.editor_windows:
            self.editor_windows.remove(editor)

    def _show_repeat_diff(self, diff_result: RepeatDiffResult) -> None:
        dialog = RepeatDiffDialog(
            diff_result=diff_result,
            clipboard=self.clipboard,
            file_manager=self.file_manager,
        )
        dialog.exec()

    def _is_recording(self) -> bool:
        return self.region_recorder is not None and self.region_recorder.is_running

    def _is_saving_mp4(self) -> bool:
        return self.region_recorder is not None and self.region_recorder.is_saving_mp4

    @pyqtSlot()
    def toggle_clipboard_history(self) -> None:
        if self.clipboard_history_window is None:
            self.clipboard_history_window = ClipboardHistoryWindow(self.clipboard)
        self.clipboard_history_window.toggle()

    @pyqtSlot(bool)
    def _on_startup_toggled(self, enabled: bool) -> None:
        success = set_startup(enabled)
        if success:
            self.settings.set(enabled, "general", "start_with_windows")
            state = "등록" if enabled else "해제"
            self.tray.show_message("Callcap", f"시작 프로그램에 {state}되었습니다.")
        else:
            self.tray.set_startup_checked(not enabled)
            self.tray.show_message("Callcap", "시작 프로그램 설정에 실패했습니다.")

    # ------------------------------------------------------------------
    # Ad system
    # ------------------------------------------------------------------

    def _show_startup_ad(self) -> None:
        if self._ad_manager.should_show_ad():
            self._show_ad()

    def _show_capture_ad(self) -> None:
        self._show_ad()

    def _show_ad(self) -> None:
        if self._ad_popup is not None:
            return
        ad_data = self._ad_manager.get_ad_data()
        popup = AdPopupWindow(ad_data)
        popup.ad_clicked.connect(lambda ad_id: self._ad_manager.record_ad_clicked(ad_id))
        popup.suppressed_today.connect(self._ad_manager.suppress_today)
        popup.destroyed.connect(lambda: setattr(self, '_ad_popup', None))
        self._ad_popup = popup
        popup.show()
        self._ad_manager.record_ad_shown()

    # ------------------------------------------------------------------
    # Auto-update
    # ------------------------------------------------------------------

    @pyqtSlot(str, str, str)
    def _on_update_available(self, version: str, download_url: str, notes: str) -> None:
        dialog = UpdateDialog(
            current_version=CURRENT_VERSION,
            new_version=version,
            download_url=download_url,
            release_notes=notes,
            updater=self._updater,
        )
        dialog.exec()

    @pyqtSlot()
    def shutdown(self) -> None:
        if self._is_saving_mp4():
            self.tray.show_message("Callcap", "MP4 is being saved. Quit after it finishes.")
            return
        self.hotkeys.unregister_all()
        if self._is_recording():
            self.region_recorder.stop()
        self._cleanup_recorder()
        self._hide_mp4_progress()
        if self.clipboard_history_window is not None:
            self.clipboard_history_window.close()
        self._reset_toolbar()
        for pin in list(self.pin_windows):
            pin.close()
        self.pin_windows.clear()
        if self.selector is not None:
            self.selector.close()
        self.tray.tray.hide()
        self.app.quit()


def apply_styles(app: QApplication) -> None:
    style_path = Path("ui/styles.qss")
    if style_path.exists():
        app.setStyleSheet(style_path.read_text(encoding="utf-8"))


def resolve_config_path() -> Path:
    if not getattr(sys, "frozen", False):
        return Path("config.json")

    appdata = os.environ.get("APPDATA")
    base_dir = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
    config_dir = base_dir / "Callcap"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    legacy_path = Path(os.path.dirname(sys.executable)) / "config.json"
    if not config_path.exists() and legacy_path.exists():
        try:
            shutil.copy2(legacy_path, config_path)
        except OSError:
            pass

    return config_path


_instance_mutex = None  # Module-level to keep handle alive


def configure_ffmpeg_env() -> None:
    if os.environ.get("IMAGEIO_FFMPEG_EXE"):
        return

    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        bundled_dir = meipass / "imageio_ffmpeg" / "binaries"
        exe_dir = Path(sys.executable).parent
        fallback_dir = exe_dir / "imageio_ffmpeg" / "binaries"
        for directory in (bundled_dir, fallback_dir):
            if not directory.exists():
                continue
            if sys.platform == "win32":
                candidates.extend(sorted(directory.glob("ffmpeg*.exe")))
            else:
                candidates.extend(
                    sorted(
                        p for p in directory.glob("ffmpeg*") if p.is_file() and os.access(p, os.X_OK)
                    )
                )
    else:
        try:
            import imageio_ffmpeg.binaries as ffmpeg_binaries

            package_dir = Path(ffmpeg_binaries.__file__).resolve().parent
            if sys.platform == "win32":
                candidates.extend(sorted(package_dir.glob("ffmpeg*.exe")))
            else:
                candidates.extend(
                    sorted(
                        p for p in package_dir.glob("ffmpeg*") if p.is_file() and os.access(p, os.X_OK)
                    )
                )
        except Exception:
            pass

    if candidates:
        os.environ["IMAGEIO_FFMPEG_EXE"] = str(candidates[0])
        return

    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_in_path


def _ensure_single_instance() -> bool:
    """Prevent multiple instances using a Windows named Mutex."""
    global _instance_mutex
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        mutex = kernel32.CreateMutexW(None, True, "Callcap_SingleInstance_Mutex")
        last_err = ctypes.get_last_error()
        if mutex in (0, None):
            return True  # Allow running if CreateMutex failed
        if last_err == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(mutex)
            return False
        _instance_mutex = mutex  # Keep alive for process lifetime
        return True
    except Exception:
        return True  # Allow running on error


def main() -> int:
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
    configure_ffmpeg_env()

    app = QApplication(sys.argv)
    QApplication.setQuitOnLastWindowClosed(False)

    if not _ensure_single_instance():
        QMessageBox.information(
            None,
            "Callcap",
            "Callcap is already running.\nUse the tray icon to continue.",
        )
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "Callcap", "System tray is not available on this system.")
        return 1

    apply_styles(app)

    try:
        controller = CallcapController(app, config_path=resolve_config_path())
    except Exception as exc:
        QMessageBox.critical(None, "Callcap", f"Startup failed:\n{exc}")
        return 1

    app.aboutToQuit.connect(controller.hotkeys.unregister_all)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
