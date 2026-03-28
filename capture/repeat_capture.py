from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage


@dataclass
class RepeatDiffResult:
    diff_image: QImage
    changed_pixels: int
    total_pixels: int
    changed_ratio: float
    changed_bounds: QRect


class RepeatCapture:
    def __init__(self) -> None:
        self._last_region: QRect | None = None
        self._last_image: QImage | None = None
        self._difference_threshold = 25

    def set_last_capture(self, rect: QRect, image: QImage) -> None:
        self._last_region = QRect(rect)
        self._last_image = image.copy()

    def get_last_region(self) -> QRect | None:
        return QRect(self._last_region) if self._last_region else None

    def has_last_capture(self) -> bool:
        return self._last_region is not None and self._last_image is not None

    def compare_with_last(self, current_image: QImage) -> RepeatDiffResult | None:
        if self._last_image is None:
            return None
        if (
            self._last_image.width() != current_image.width()
            or self._last_image.height() != current_image.height()
        ):
            return None

        previous = self._qimage_to_rgba_array(self._last_image)
        current = self._qimage_to_rgba_array(current_image)
        color_diff = np.abs(current[:, :, :3].astype(np.int16) - previous[:, :, :3].astype(np.int16))
        changed_mask = np.any(color_diff >= self._difference_threshold, axis=2)

        changed_pixels = int(changed_mask.sum())
        total_pixels = int(changed_mask.size)
        changed_ratio = (changed_pixels / total_pixels) if total_pixels else 0.0

        highlighted = current.copy()
        unchanged_mask = ~changed_mask
        highlighted[unchanged_mask, :3] = (highlighted[unchanged_mask, :3] * 0.85).astype(np.uint8)

        if changed_pixels > 0:
            red = np.array([255, 64, 64], dtype=np.float32)
            blended = (
                highlighted[changed_mask, :3].astype(np.float32) * 0.35
                + red * 0.65
            ).astype(np.uint8)
            highlighted[changed_mask, :3] = blended
            highlighted[changed_mask, 3] = 255
            ys, xs = np.where(changed_mask)
            bounds = QRect(
                int(xs.min()),
                int(ys.min()),
                int(xs.max() - xs.min() + 1),
                int(ys.max() - ys.min() + 1),
            )
        else:
            bounds = QRect()

        height, width, _ = highlighted.shape
        diff_image = QImage(
            highlighted.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()

        return RepeatDiffResult(
            diff_image=diff_image,
            changed_pixels=changed_pixels,
            total_pixels=total_pixels,
            changed_ratio=changed_ratio,
            changed_bounds=bounds,
        )

    @staticmethod
    def _qimage_to_rgba_array(image: QImage) -> np.ndarray:
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width = rgba.width()
        height = rgba.height()
        bytes_per_line = rgba.bytesPerLine()
        ptr = rgba.bits()
        ptr.setsize(rgba.sizeInBytes())
        raw = np.frombuffer(ptr, dtype=np.uint8).reshape((height, bytes_per_line))
        return raw[:, : width * 4].reshape((height, width, 4)).copy()
