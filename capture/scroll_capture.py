"""Scroll capture: scroll a region with the mouse wheel and stitch the frames.

Each step sends wheel notches to the window under the region, grabs the
region again, and finds how far the content moved by matching row
signatures. Rows that do not move (a sticky header or footer) are detected
per step and kept only once.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import numpy as np
from PyQt6.QtCore import QObject, QPoint, QRect, QTimer, pyqtSignal
from PyQt6.QtGui import QImage

from capture import window_finder
from capture.screen_capture import ScreenCaptureService

_BINS = 48
_STATIC_TOL = 2.0  # mean abs diff (0..255) below which a row counts as unchanged
_MATCH_TOL = 6.0  # best overlap must be at least this close
_WHEEL_DELTA = 120
_MOUSEEVENTF_WHEEL = 0x0800


def qimage_to_rgb(image: QImage) -> np.ndarray:
    img = image.convertToFormat(QImage.Format.Format_RGB32)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
    return arr[:, : img.width(), :3].copy()  # BGR order, which is all we need


def rgb_to_qimage(arr: np.ndarray) -> QImage:
    h, w, _ = arr.shape
    bgra = np.empty((h, w, 4), np.uint8)
    bgra[..., :3] = arr
    bgra[..., 3] = 255
    image = QImage(bgra.data, w, h, w * 4, QImage.Format.Format_RGB32)
    return image.copy()


def row_signatures(arr: np.ndarray) -> np.ndarray:
    """Each row reduced to _BINS column-band means of grey levels."""
    grey = arr.astype(np.float32).mean(axis=2)
    h, w = grey.shape
    bins = min(_BINS, w)
    edges = np.linspace(0, w, bins + 1).astype(int)
    return np.stack([grey[:, edges[i]:max(edges[i] + 1, edges[i + 1])].mean(axis=1) for i in range(bins)], axis=1)


def static_bands(sig_a: np.ndarray, sig_b: np.ndarray) -> tuple[int, int]:
    """Rows unchanged at the top and bottom between two frames."""
    same = np.abs(sig_a - sig_b).mean(axis=1) < _STATIC_TOL
    h = len(same)
    top = 0
    while top < h and same[top]:
        top += 1
    bottom = 0
    while bottom < h - top and same[h - 1 - bottom]:
        bottom += 1
    return top, bottom


def find_shift(sig_a: np.ndarray, sig_b: np.ndarray, top: int, bottom: int, hint: int | None) -> tuple[int, float] | None:
    """How many rows the moving area scrolled up from frame A to frame B."""
    h = len(sig_a)
    ma = sig_a[top:h - bottom]
    mb = sig_b[top:h - bottom]
    n = len(ma)
    if n < 24:
        return None
    min_overlap = max(12, n // 6)
    scores = np.full(n, np.inf, dtype=np.float32)
    for dy in range(1, n - min_overlap + 1):
        scores[dy] = np.abs(mb[: n - dy] - ma[dy:]).mean()
    best = float(scores.min())
    if not np.isfinite(best) or best > _MATCH_TOL:
        return None
    near = np.flatnonzero(scores <= best + 0.5)
    if hint is not None and len(near) > 1:
        dy = int(near[np.argmin(np.abs(near - hint))])
    else:
        dy = int(np.argmin(scores))
    return dy, float(scores[dy])


class ScrollStitcher:
    """Accumulates frames into one tall image."""

    def __init__(self, first: np.ndarray, max_height: int = 30000) -> None:
        self.frames = 1
        self.max_height = max_height
        self._prev = first
        self._prev_sig = row_signatures(first)
        self._body: list[np.ndarray] | None = None
        self._first = first
        self._footer_rows = 0
        self._last_shift: int | None = None

    @property
    def height(self) -> int:
        if self._body is None:
            return self._first.shape[0]
        return sum(part.shape[0] for part in self._body) + self._footer_rows

    def add(self, frame: np.ndarray) -> str:
        """Returns "moved", "same" (nothing scrolled) or "lost" (no overlap)."""
        sig = row_signatures(frame)
        top, bottom = static_bands(self._prev_sig, sig)
        h = frame.shape[0]
        if top + bottom >= h - 4:
            return "same"
        found = find_shift(self._prev_sig, sig, top, bottom, self._last_shift)
        if found is None:
            return "lost"
        dy, _score = found
        n = h - top - bottom
        if self._body is None:
            # Drop the first frame's footer; the last frame supplies it.
            self._body = [self._first[: h - bottom]]
        new_rows = frame[top + n - dy : h - bottom]
        if len(new_rows):
            self._body.append(new_rows)
        self._footer_rows = bottom
        self._prev = frame
        self._prev_sig = sig
        self._last_shift = dy
        self.frames += 1
        return "moved"

    def result(self) -> np.ndarray:
        if self._body is None:
            return self._first
        parts = list(self._body)
        if self._footer_rows:
            parts.append(self._prev[self._prev.shape[0] - self._footer_rows :])
        tall = np.concatenate(parts, axis=0)
        return tall[: self.max_height]


class ScrollCaptureSession(QObject):
    progress = pyqtSignal(int, int)  # frames, height
    finished = pyqtSignal(QImage, str)  # image, reason
    failed = pyqtSignal(str)

    def __init__(
        self,
        capture_service: ScreenCaptureService,
        rect: QRect,
        notches: int = 3,
        settle_ms: int = 450,
        max_frames: int = 80,
        max_height: int = 30000,
    ) -> None:
        super().__init__()
        self._capture = capture_service
        self._rect = QRect(rect)
        self._notches = max(1, notches)
        self._settle_ms = settle_ms
        self._max_frames = max_frames
        self._max_height = max_height
        self._stitcher: ScrollStitcher | None = None
        self._same_count = 0
        self._running = False
        self._stop_requested = False
        self._saved_cursor: QPoint | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._step_capture)

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        try:
            first = qimage_to_rgb(self._capture.capture_region(self._rect))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self._stitcher = ScrollStitcher(first, self._max_height)
        self._running = True
        self._save_cursor()
        self._scroll_once()
        self._timer.start(self._settle_ms)

    def stop(self) -> None:
        self._stop_requested = True

    def _save_cursor(self) -> None:
        if sys.platform != "win32":
            return
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        self._saved_cursor = QPoint(pt.x, pt.y)

    def _restore_cursor(self) -> None:
        if sys.platform == "win32" and self._saved_cursor is not None:
            ctypes.windll.user32.SetCursorPos(self._saved_cursor.x(), self._saved_cursor.y())

    def _scroll_once(self) -> None:
        if sys.platform != "win32":
            return
        center = window_finder.logical_to_physical(self._rect.center())
        user32 = ctypes.windll.user32
        user32.SetCursorPos(center.x(), center.y())
        # Negative delta scrolls down; mouse_event takes it as a signed DWORD.
        user32.mouse_event(_MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_int(-_WHEEL_DELTA * self._notches), 0)

    def _step_capture(self) -> None:
        if not self._running or self._stitcher is None:
            return
        try:
            frame = qimage_to_rgb(self._capture.capture_region(self._rect))
        except Exception as exc:
            self._finish(f"캡처 실패: {exc}")
            return
        state = self._stitcher.add(frame)
        self.progress.emit(self._stitcher.frames, self._stitcher.height)

        if self._stop_requested:
            self._finish("stopped")
            return
        if state == "same":
            self._same_count += 1
            if self._same_count >= 2:
                self._finish("end")
                return
        elif state == "lost":
            self._finish("lost")
            return
        else:
            self._same_count = 0
            frame_h = frame.shape[0]
            shift = self._stitcher._last_shift or 0
            # Too big a jump risks losing the overlap next time; slow down.
            if shift > frame_h * 0.6 and self._notches > 1:
                self._notches -= 1
        if self._stitcher.frames >= self._max_frames or self._stitcher.height >= self._max_height:
            self._finish("limit")
            return
        self._scroll_once()
        self._timer.start(self._settle_ms)

    def _finish(self, reason: str) -> None:
        self._running = False
        self._timer.stop()
        self._restore_cursor()
        if self._stitcher is None:
            self.failed.emit(reason)
            return
        image = rgb_to_qimage(self._stitcher.result())
        self.finished.emit(image, reason)
