"""auto_updater.py – Background update checker and installer for Callcap.

Usage from main.py::

    self.updater = AutoUpdater()
    self.updater.update_available.connect(self._on_update_available)
    QTimer.singleShot(5000, self.updater.check_for_updates)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import requests
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

# ---------------------------------------------------------------------------
# Public constant – bump this on every release build.
# ---------------------------------------------------------------------------
CURRENT_VERSION = "1.0.0"

# GitHub repository to query.  Change owner/repo before shipping.
_GITHUB_OWNER = "huhyoundo"
_GITHUB_REPO  = "captureform"
_API_URL       = f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/latest"

# Request timeout (seconds) for all outbound HTTP calls.
_NETWORK_TIMEOUT = 15

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_version(version_str: str) -> tuple[int, ...]:
    """Convert 'v1.2.3' or '1.2.3' to (1, 2, 3).

    Non-numeric segments are treated as 0 so pre-release tags such as
    '1.2.3-beta' compare lower than '1.2.3'.
    """
    clean = version_str.lstrip("vV").split("-")[0]
    parts: list[int] = []
    for part in clean.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    # Normalise to at least three components.
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _is_newer(remote: str, local: str) -> bool:
    """Return True when *remote* is strictly greater than *local*."""
    return _parse_version(remote) > _parse_version(local)


def _find_setup_asset(assets: list[dict]) -> Optional[dict]:
    """Return the first asset that looks like a Windows setup executable."""
    for asset in assets:
        name: str = asset.get("name", "").lower()
        if name.endswith(".exe") and ("setup" in name or "install" in name):
            return asset
    # Fallback: any .exe asset
    for asset in assets:
        if asset.get("name", "").lower().endswith(".exe"):
            return asset
    return None


# ---------------------------------------------------------------------------
# Worker – runs entirely on a background QThread
# ---------------------------------------------------------------------------

class _UpdateCheckWorker(QObject):
    """Performs network I/O off the main thread.

    Signals
    -------
    update_found(version, download_url, release_notes)
        Emitted when a newer release is detected.
    no_update()
        Emitted when the current version is up to date.
    check_error(message)
        Emitted on any network or parsing failure.
    download_progress(percent)
        Emitted periodically during the file download (0–100).
    download_finished(file_path)
        Emitted when the installer has been saved to *file_path*.
    download_error(message)
        Emitted when the download fails.
    """

    update_found      = pyqtSignal(str, str, str)   # version, url, notes
    no_update         = pyqtSignal()
    check_error       = pyqtSignal(str)
    download_progress = pyqtSignal(int)             # percent 0-100
    download_finished = pyqtSignal(str)             # absolute file path
    download_error    = pyqtSignal(str)

    def __init__(self, download_url: str = "") -> None:
        super().__init__()
        self._download_url = download_url

    # ------------------------------------------------------------------
    # Slots invoked by the owning AutoUpdater via QThread signals
    # ------------------------------------------------------------------

    @pyqtSlot()
    def run_check(self) -> None:
        """Query the GitHub API and compare versions."""
        log.info("Checking for updates against %s", _API_URL)
        try:
            response = requests.get(
                _API_URL,
                timeout=_NETWORK_TIMEOUT,
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Update check network error: %s", exc)
            self.check_error.emit(str(exc))
            return

        try:
            data = response.json()
        except ValueError as exc:
            log.warning("Update check JSON parse error: %s", exc)
            self.check_error.emit(f"Invalid response from GitHub: {exc}")
            return

        remote_version: str = data.get("tag_name", "").lstrip("vV")
        if not remote_version:
            log.warning("GitHub response missing tag_name field")
            self.check_error.emit("Could not determine remote version.")
            return

        release_notes: str = data.get("body") or ""
        assets: list[dict] = data.get("assets", [])
        setup_asset = _find_setup_asset(assets)

        if setup_asset is None:
            log.info("No Windows installer asset found in release %s", remote_version)
            # Treat as no update – we cannot install without an asset.
            self.no_update.emit()
            return

        download_url: str = setup_asset.get("browser_download_url", "")

        if _is_newer(remote_version, CURRENT_VERSION):
            log.info(
                "Update available: %s → %s  url=%s",
                CURRENT_VERSION, remote_version, download_url,
            )
            self.update_found.emit(remote_version, download_url, release_notes)
        else:
            log.info("Already up to date (%s)", CURRENT_VERSION)
            self.no_update.emit()

    @pyqtSlot()
    def run_download(self) -> None:
        """Stream-download the installer to a temp file."""
        if not self._download_url:
            self.download_error.emit("No download URL provided.")
            return

        log.info("Downloading installer: %s", self._download_url)
        try:
            response = requests.get(
                self._download_url,
                stream=True,
                timeout=_NETWORK_TIMEOUT,
                headers={"Accept": "application/octet-stream"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Installer download error: %s", exc)
            self.download_error.emit(str(exc))
            return

        total_bytes = int(response.headers.get("content-length", 0))

        # Write to a named temp file that persists after closing.
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".exe", prefix="callcap_setup_")
        except OSError as exc:
            log.error("Cannot create temp file: %s", exc)
            self.download_error.emit(f"Cannot create temp file: {exc}")
            return

        downloaded = 0
        last_reported = -1

        try:
            with os.fdopen(fd, "wb") as fh:
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes > 0:
                        percent = int(downloaded * 100 / total_bytes)
                    else:
                        # Unknown size: pulse every 64 KB, cap at 99 until done.
                        percent = min(99, int(downloaded / 1_048_576))
                    if percent != last_reported:
                        self.download_progress.emit(percent)
                        last_reported = percent
        except OSError as exc:
            log.error("Write error during download: %s", exc)
            self.download_error.emit(f"Write error: {exc}")
            # Clean up the partial file.
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            return

        self.download_progress.emit(100)
        log.info("Download complete: %s (%d bytes)", tmp_path, downloaded)
        self.download_finished.emit(tmp_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class AutoUpdater(QObject):
    """Orchestrates version checks and installer downloads for Callcap.

    All network operations run on a dedicated QThread; signals are emitted
    back to the main thread for safe UI interaction.

    Signals
    -------
    update_available(version, download_url, release_notes)
        Emitted when a newer release is found on GitHub.
    no_update_available()
        Emitted when the installed version is current.
    check_failed(message)
        Emitted when the version check cannot complete.
    download_progress(percent)
        Integer 0-100 progress during installer download.
    download_complete(file_path)
        Absolute path of the downloaded installer exe.
    download_failed(message)
        Emitted when the installer download fails.
    """

    update_available    = pyqtSignal(str, str, str)  # version, url, notes
    no_update_available = pyqtSignal()
    check_failed        = pyqtSignal(str)
    download_progress   = pyqtSignal(int)
    download_complete   = pyqtSignal(str)
    download_failed     = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _UpdateCheckWorker | None = None
        self._pending_download_url: str = ""

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    @pyqtSlot()
    def check_for_updates(self) -> None:
        """Begin an asynchronous version check.

        Safe to call from the main thread.  If a check is already running
        the call is silently ignored.
        """
        if self._thread is not None and self._thread.isRunning():
            log.debug("Update check already in progress; ignoring duplicate request.")
            return

        log.debug("Spawning update-check thread.")
        self._start_worker(download_url="", slot="run_check")

    def start_download(self, download_url: str) -> None:
        """Begin downloading the installer from *download_url*.

        Safe to call from the main thread (e.g. from an UpdateDialog button).
        """
        if not download_url:
            log.warning("start_download called with empty URL.")
            return
        if self._thread is not None and self._thread.isRunning():
            log.debug("Download already in progress; ignoring duplicate request.")
            return

        log.debug("Spawning download thread for %s", download_url)
        self._start_worker(download_url=download_url, slot="run_download")

    @staticmethod
    def install_update(installer_path: str) -> None:
        """Launch the installer silently and quit the application.

        Uses the Inno Setup ``/SILENT`` flag.  The current process exits
        immediately so the installer can overwrite files in use.
        """
        path = Path(installer_path)
        if not path.exists():
            log.error("Installer not found at %s", installer_path)
            return

        log.info("Launching installer: %s", installer_path)
        try:
            subprocess.Popen(
                [str(path), "/SILENT"],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except OSError as exc:
            log.error("Failed to launch installer: %s", exc)
            return

        # Give the installer a moment to start, then exit cleanly.
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()
        else:
            sys.exit(0)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _start_worker(self, download_url: str, slot: str) -> None:
        """Create a fresh worker + thread and connect all signals."""
        worker = _UpdateCheckWorker(download_url=download_url)
        thread = QThread(self)

        worker.moveToThread(thread)

        # Wire worker signals to updater signals so callers only talk to AutoUpdater.
        worker.update_found.connect(self.update_available)
        worker.no_update.connect(self.no_update_available)
        worker.check_error.connect(self.check_failed)
        worker.download_progress.connect(self.download_progress)
        worker.download_finished.connect(self.download_complete)
        worker.download_error.connect(self.download_failed)

        # Start the appropriate slot when the thread begins.
        target = getattr(worker, slot)
        thread.started.connect(target)

        # Clean up once done.
        worker.no_update.connect(thread.quit)
        worker.update_found.connect(thread.quit)
        worker.check_error.connect(thread.quit)
        worker.download_finished.connect(thread.quit)
        worker.download_error.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)

        self._worker = worker
        self._thread = thread
        thread.start()

    @pyqtSlot()
    def _on_thread_finished(self) -> None:
        """Release references so the thread and worker can be GC'd."""
        log.debug("Update thread finished; cleaning up.")
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
