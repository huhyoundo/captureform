from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QObject, QRect, Qt, QTimer, pyqtSignal

from capture.screen_capture import ScreenCaptureService


class RegionRecordingSession(QObject):
    finished = pyqtSignal(str, int, float)
    failed = pyqtSignal(str)
    mp4_finished = pyqtSignal(str)
    mp4_failed = pyqtSignal(str)

    def __init__(
        self,
        capture_service: ScreenCaptureService,
        rect: QRect,
        output_path: Path,
        fps: int = 24,
    ) -> None:
        super().__init__()
        self._capture_service = capture_service
        self._rect = rect.normalized()
        self._output_path = Path(output_path)
        self._fps = max(1, min(60, int(fps)))
        self._interval_ms = max(1, int(round(1000 / self._fps)))

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._capture_frame)

        self._running = False
        self._capturing_frame = False
        self._tmp_dir: Path | None = None
        self._frame_paths: list[Path] = []
        self._started_at = 0.0
        self._recorded_elapsed = 0.0

        self._audio_path: Path | None = None
        self._audio_thread: threading.Thread | None = None
        self._audio_stop_event = threading.Event()
        self._mp4_thread: threading.Thread | None = None
        self._mp4_saving = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def has_frames(self) -> bool:
        return bool(self._frame_paths) and self._tmp_dir is not None

    @property
    def is_saving_mp4(self) -> bool:
        return self._mp4_saving

    def start(self) -> None:
        if self._running:
            return
        if self._rect.width() <= 1 or self._rect.height() <= 1:
            self.failed.emit("Recording area is too small.")
            return

        self._tmp_dir = Path(tempfile.mkdtemp(prefix="supercapture_record_"))
        self._frame_paths = []
        self._started_at = time.perf_counter()
        self._recorded_elapsed = 0.0
        self._running = True

        self._start_audio_capture()
        self._capture_frame()
        if self._running:
            self._timer.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._timer.stop()
        self._running = False
        self._stop_audio_capture()
        self._recorded_elapsed = max(0.0, time.perf_counter() - self._started_at)
        self._finalize_recording()

    def _start_audio_capture(self) -> None:
        if self._tmp_dir is None:
            return
        self._audio_path = self._tmp_dir / "audio.wav"
        self._audio_stop_event.clear()
        self._audio_thread = threading.Thread(target=self._record_audio, daemon=True)
        self._audio_thread.start()

    def _stop_audio_capture(self) -> None:
        if self._audio_thread is not None:
            self._audio_stop_event.set()
            self._audio_thread.join(timeout=5.0)
            self._audio_thread = None

    def _record_audio(self) -> None:
        try:
            import pyaudiowpatch as pyaudio  # type: ignore[import-untyped]

            p = pyaudio.PyAudio()
            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_speakers = p.get_device_info_by_index(
                    wasapi_info["defaultOutputDevice"]
                )

                if not default_speakers["isLoopbackDevice"]:
                    for loopback in p.get_loopback_device_info_generator():
                        if default_speakers["name"] in loopback["name"]:
                            default_speakers = loopback
                            break
                    else:
                        self._audio_path = None
                        return

                channels = max(1, min(2, int(default_speakers.get("maxInputChannels", 2))))
                rate = int(default_speakers.get("defaultSampleRate", 48000))
                if rate <= 0:
                    rate = 48000
                sample_width = pyaudio.get_sample_size(pyaudio.paInt16)

                wf = wave.open(str(self._audio_path), "wb")
                wf.setnchannels(channels)
                wf.setsampwidth(sample_width)
                wf.setframerate(rate)

                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=rate,
                    frames_per_buffer=1024,
                    input=True,
                    input_device_index=default_speakers["index"],
                )

                try:
                    while not self._audio_stop_event.is_set():
                        data = stream.read(1024, exception_on_overflow=False)
                        wf.writeframes(data)
                finally:
                    stream.stop_stream()
                    stream.close()
                    wf.close()
            finally:
                p.terminate()
        except Exception:
            self._audio_path = None

    def _capture_frame(self) -> None:
        if not self._running or self._capturing_frame:
            return

        self._capturing_frame = True
        try:
            if self._tmp_dir is None:
                raise RuntimeError("Temporary recording directory is not initialized.")

            image = self._capture_service.capture_region(self._rect)
            if image.isNull():
                raise RuntimeError("Failed to capture a recording frame.")

            frame_path = self._tmp_dir / f"frame_{len(self._frame_paths):06d}.png"
            if not image.save(str(frame_path), "PNG"):
                raise RuntimeError("Failed to write a recording frame to disk.")
            self._frame_paths.append(frame_path)
        except Exception as exc:
            self._timer.stop()
            self._running = False
            self._stop_audio_capture()
            self._cleanup_tmp_dir()
            self.failed.emit(str(exc))
        finally:
            self._capturing_frame = False

    def _finalize_recording(self) -> None:
        if not self._frame_paths:
            self._cleanup_tmp_dir()
            self.failed.emit("No recording frames were captured.")
            return

        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        elapsed = self._recorded_elapsed or max(0.0, time.perf_counter() - self._started_at)
        frame_duration_ms = max(1, int(round((elapsed / max(1, len(self._frame_paths))) * 1000.0)))

        first_image: Image.Image | None = None
        append_images: list[Image.Image] = []

        try:
            first_image = Image.open(self._frame_paths[0])
            for frame_path in self._frame_paths[1:]:
                append_images.append(Image.open(frame_path))

            first_image.save(
                str(self._output_path),
                save_all=True,
                append_images=append_images,
                duration=frame_duration_ms,
                loop=0,
                optimize=False,
                disposal=2,
            )
        except Exception as exc:
            self._cleanup_tmp_dir()
            self.failed.emit(f"Failed to save recording: {exc}")
            return
        finally:
            if first_image is not None:
                first_image.close()
            for image in append_images:
                image.close()

        self.finished.emit(str(self._output_path), len(self._frame_paths), elapsed)

    def save_as_mp4(self, output_path: Path) -> None:
        if not self.has_frames:
            self.mp4_failed.emit("No frames available for MP4 conversion.")
            return
        if self._mp4_saving:
            self.mp4_failed.emit("MP4 conversion is already in progress.")
            return

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._mp4_saving = True
        self._mp4_thread = threading.Thread(
            target=self._save_as_mp4_worker,
            args=(output_path,),
            daemon=True,
        )
        self._mp4_thread.start()

    def _save_as_mp4_worker(self, output_path: Path) -> None:
        try:
            if self._tmp_dir is None:
                raise RuntimeError("Temporary recording directory is not available.")

            frame_count = len(self._frame_paths)
            elapsed = self._recorded_elapsed
            if elapsed <= 0 and frame_count > 0:
                elapsed = frame_count / float(max(1, self._fps))
            effective_fps = frame_count / elapsed if elapsed > 0 else float(self._fps)
            effective_fps = max(1.0, min(60.0, effective_fps))
            frame_glob = self._tmp_dir / "frame_%06d.png"
            audio_path = self._audio_path

            ffmpeg = self._resolve_ffmpeg_exe()

            cmd = [
                str(ffmpeg), "-y",
                "-framerate", f"{effective_fps:.6f}",
                "-i", str(frame_glob),
            ]

            has_audio = (
                audio_path is not None
                and audio_path.exists()
                and audio_path.stat().st_size > 44
            )

            if has_audio:
                cmd.extend(["-i", str(audio_path)])

            cmd.extend([
                "-c:v", "libx264",
                "-crf", "16",
                "-preset", "medium",
                "-pix_fmt", "yuv420p",
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            ])

            if has_audio:
                cmd.extend([
                    "-c:a", "aac",
                    "-ac", "2",
                    "-ar", "48000",
                    "-b:a", "320k",
                    "-af", "aresample=async=1:first_pts=0",
                    "-shortest",
                ])

            cmd.extend(["-movflags", "+faststart"])

            cmd.append(str(output_path))

            run_kwargs: dict[str, object] = {
                "check": True,
                "capture_output": True,
                "stdin": subprocess.DEVNULL,
            }
            run_kwargs.update(self._hidden_subprocess_kwargs())
            subprocess.run(
                cmd,
                **run_kwargs,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode(errors="replace") if exc.stderr else str(exc)
            self.mp4_failed.emit(f"Failed to save MP4: {stderr}")
        except Exception as exc:
            self.mp4_failed.emit(f"Failed to save MP4: {exc}")
        else:
            self.mp4_finished.emit(str(output_path))
        finally:
            self._mp4_saving = False
            self._mp4_thread = None

    @staticmethod
    def _hidden_subprocess_kwargs() -> dict[str, object]:
        if sys.platform != "win32":
            return {}

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return {
            "startupinfo": startupinfo,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }

    @staticmethod
    def _resolve_ffmpeg_exe() -> str:
        env_exe = os.environ.get("IMAGEIO_FFMPEG_EXE")
        if env_exe:
            return env_exe

        candidates: list[Path] = []

        if getattr(sys, "frozen", False):
            meipass = Path(getattr(sys, "_MEIPASS", ""))
            bundled_dir = meipass / "imageio_ffmpeg" / "binaries"
            if bundled_dir.exists():
                if sys.platform == "win32":
                    candidates.extend(sorted(bundled_dir.glob("ffmpeg*.exe")))
                else:
                    candidates.extend(
                        sorted(
                            p for p in bundled_dir.glob("ffmpeg*") if p.is_file() and os.access(p, os.X_OK)
                        )
                    )
            exe_dir = Path(sys.executable).parent
            fallback_dir = exe_dir / "imageio_ffmpeg" / "binaries"
            if fallback_dir.exists():
                if sys.platform == "win32":
                    candidates.extend(sorted(fallback_dir.glob("ffmpeg*.exe")))
                else:
                    candidates.extend(
                        sorted(
                            p for p in fallback_dir.glob("ffmpeg*") if p.is_file() and os.access(p, os.X_OK)
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
            resolved = str(candidates[0])
            os.environ["IMAGEIO_FFMPEG_EXE"] = resolved
            return resolved

        ffmpeg_from_path = shutil.which("ffmpeg")
        if ffmpeg_from_path:
            os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_from_path
            return ffmpeg_from_path

        raise RuntimeError("FFmpeg executable was not found.")

    def cleanup(self) -> None:
        if self._mp4_saving:
            return
        self._cleanup_tmp_dir()

    def _cleanup_tmp_dir(self) -> None:
        if self._tmp_dir is not None:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None
            self._frame_paths = []
            self._audio_path = None
            self._recorded_elapsed = 0.0
