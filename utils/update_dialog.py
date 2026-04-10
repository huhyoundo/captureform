"""update_dialog.py – Update-available dialog for Callcap.

Displays the new version, release notes, and controls to download/install
or defer the update.  Connects directly to an AutoUpdater instance.

Typical usage::

    def _on_update_available(self, version, download_url, notes):
        dlg = UpdateDialog(
            current_version=CURRENT_VERSION,
            new_version=version,
            download_url=download_url,
            release_notes=notes,
            updater=self.updater,
        )
        dlg.exec()
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """Modal dialog shown when a new Callcap release is available.

    Parameters
    ----------
    current_version:
        The version string currently installed, e.g. ``"1.0.0"``.
    new_version:
        The version string of the release on GitHub, e.g. ``"1.1.0"``.
    download_url:
        Direct URL to the Windows installer ``.exe``.
    release_notes:
        Markdown or plain-text body from the GitHub release.
    updater:
        The :class:`~utils.auto_updater.AutoUpdater` instance.  The dialog
        connects to its ``download_progress`` and ``download_complete``
        signals so it can show live progress.
    parent:
        Optional parent widget.
    """

    def __init__(
        self,
        current_version: str,
        new_version: str,
        download_url: str,
        release_notes: str,
        updater,  # AutoUpdater – avoid circular import with a plain annotation
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._download_url = download_url
        self._updater = updater
        self._installer_path: str = ""

        self._build_ui(current_version, new_version, release_notes)
        self._connect_updater()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(
        self,
        current_version: str,
        new_version: str,
        release_notes: str,
    ) -> None:
        self.setWindowTitle("Callcap 업데이트")
        self.setModal(True)
        self.resize(450, 350)
        self.setMinimumSize(420, 320)
        # Prevent resizing so the layout stays predictable.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        # ── Title ────────────────────────────────────────────────────
        title_label = QLabel("새 버전이 출시되었습니다")
        title_label.setObjectName("dialogTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # ── Version row ──────────────────────────────────────────────
        version_row = QHBoxLayout()
        version_row.setSpacing(4)

        cur_label = QLabel(f"현재 버전:  <b>{current_version}</b>")
        arrow_label = QLabel("→")
        new_label = QLabel(f"<b style='color:#7dd3fc;'>{new_version}</b>")
        new_label.setObjectName("dialogInfo")

        version_row.addWidget(cur_label)
        version_row.addWidget(arrow_label)
        version_row.addWidget(new_label)
        version_row.addStretch(1)

        # ── Release notes ────────────────────────────────────────────
        notes_label = QLabel("변경 사항:")
        notes_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._notes_edit = QTextEdit()
        self._notes_edit.setReadOnly(True)
        self._notes_edit.setPlainText(release_notes or "릴리즈 노트가 없습니다.")
        self._notes_edit.setFixedHeight(130)

        # ── Progress bar (hidden until download starts) ───────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("%p%")
        self._progress_bar.setFixedHeight(18)
        self._progress_bar.setVisible(False)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setObjectName("dialogInfo")
        self._status_label.setVisible(False)

        # ── Buttons ──────────────────────────────────────────────────
        self._update_btn = QPushButton("지금 업데이트")
        self._update_btn.setDefault(True)
        self._update_btn.setMinimumWidth(120)

        self._later_btn = QPushButton("나중에")
        self._later_btn.setMinimumWidth(80)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self._later_btn)
        btn_row.addWidget(self._update_btn)

        # ── Main layout ──────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        layout.addWidget(title_label)
        layout.addLayout(version_row)
        layout.addWidget(notes_label)
        layout.addWidget(self._notes_edit, 1)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._status_label)
        layout.addLayout(btn_row)

        # ── Signal wiring ────────────────────────────────────────────
        self._update_btn.clicked.connect(self._on_update_clicked)
        self._later_btn.clicked.connect(self.reject)

    # ------------------------------------------------------------------
    # AutoUpdater signal connections
    # ------------------------------------------------------------------

    def _connect_updater(self) -> None:
        if self._updater is None:
            return
        self._updater.download_progress.connect(self._on_download_progress)
        self._updater.download_complete.connect(self._on_download_complete)
        self._updater.download_failed.connect(self._on_download_failed)

    def _disconnect_updater(self) -> None:
        """Safely disconnect to avoid stale connections after dialog close."""
        if self._updater is None:
            return
        try:
            self._updater.download_progress.disconnect(self._on_download_progress)
            self._updater.download_complete.disconnect(self._on_download_complete)
            self._updater.download_failed.disconnect(self._on_download_failed)
        except (RuntimeError, TypeError):
            pass  # Already disconnected or object was destroyed.

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_update_clicked(self) -> None:
        """Disable buttons, reveal the progress bar, and start the download."""
        log.info("User requested update download.")
        self._update_btn.setEnabled(False)
        self._later_btn.setEnabled(False)
        self._update_btn.setText("다운로드 중...")

        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._status_label.setText("설치 파일을 다운로드하는 중입니다...")
        self._status_label.setVisible(True)

        if self._updater is not None:
            self._updater.start_download(self._download_url)
        else:
            log.error("UpdateDialog has no updater reference; cannot start download.")
            self._on_download_failed("업데이터가 초기화되지 않았습니다.")

    @pyqtSlot(int)
    def _on_download_progress(self, percent: int) -> None:
        self._progress_bar.setValue(percent)

    @pyqtSlot(str)
    def _on_download_complete(self, file_path: str) -> None:
        """Download finished – launch the installer and close the app."""
        log.info("Download complete, launching installer: %s", file_path)
        self._installer_path = file_path

        self._progress_bar.setValue(100)
        self._status_label.setText("설치를 시작합니다. 앱이 종료됩니다...")

        self._disconnect_updater()

        # Small delay to let the label render before the process exits.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(600, self._launch_installer)

    @pyqtSlot(str)
    def _on_download_failed(self, message: str) -> None:
        log.warning("Download failed: %s", message)
        self._progress_bar.setVisible(False)
        self._status_label.setText(f"다운로드 실패: {message}")
        self._status_label.setVisible(True)

        # Re-enable so the user can retry.
        self._update_btn.setText("다시 시도")
        self._update_btn.setEnabled(True)
        self._later_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _launch_installer(self) -> None:
        from utils.auto_updater import AutoUpdater
        AutoUpdater.install_update(self._installer_path)
        # install_update calls app.quit(); this close() is a safety net.
        self.close()

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._disconnect_updater()
        super().closeEvent(event)

    def reject(self) -> None:
        log.debug("User deferred the update.")
        self._disconnect_updater()
        super().reject()
