"""Lectura Unicode, exportación atómica, streaming de video y conservación de audio."""

from __future__ import annotations

import math
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Event
from typing import Callable

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageOps

from .core import Settings, check_cancel, process_frame

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
Progress = Callable[[int, int, str], None]


def read_image(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source)
        if getattr(source, "is_animated", False):
            raise ValueError("Las imágenes animadas no son compatibles; usa un video o imagen fija.")
        alpha = None
        if "A" in oriented.getbands() or "transparency" in oriented.info:
            rgba = np.asarray(oriented.convert("RGBA"))
            alpha = rgba[..., 3].copy()
        return np.asarray(oriented.convert("RGB")).copy(), alpha


def video_info(path: Path) -> tuple[int, int, float, int]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("No se pudo abrir el video. Comprueba el formato y el códec.")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS)
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if width <= 0 or height <= 0 or not math.isfinite(fps) or fps <= 0:
            raise ValueError("El video no contiene dimensiones o fotogramas por segundo válidos.")
        return width, height, fps, max(0, count)
    finally:
        capture.release()


def read_video_frame(path: Path, index: int) -> np.ndarray:
    capture = cv2.VideoCapture(str(path))
    try:
        if index:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if not ok:
            raise ValueError("No se pudo leer este fotograma del video.")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    finally:
        capture.release()


def _check_destination(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("Elige otro nombre: el archivo original debe conservarse.")
    if not destination.parent.is_dir():
        raise ValueError("La carpeta de destino no existe.")


def export_image(source: Path, destination: Path, settings: Settings, cancel: Event | None = None) -> None:
    _check_destination(source, destination)
    if destination.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}:
        raise ValueError("Formato de imagen de salida no compatible.")
    image, alpha = read_image(source)
    result, _ = process_frame(image, settings, cancel)
    if alpha is not None and destination.suffix.lower() in {".png", ".webp", ".tif", ".tiff"}:
        result = np.dstack((result, alpha))
    handle, temporary = tempfile.mkstemp(prefix=".limpiacolor-", suffix=destination.suffix, dir=destination.parent)
    os.close(handle)
    temp_path = Path(temporary)
    try:
        options = {"quality": 95} if destination.suffix.lower() in {".jpg", ".jpeg", ".webp"} else {}
        Image.fromarray(result).save(temp_path, **options)
        check_cancel(cancel)
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def _run_ffmpeg(arguments: list[str], cancel: Event | None, log_path: Path) -> None:
    # El log va a disco: no puede llenar una tubería y bloquear el proceso.
    with log_path.open("wb") as error_log:
        process = subprocess.Popen(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", *arguments],
            stdout=subprocess.DEVNULL, stderr=error_log, creationflags=NO_WINDOW,
        )
        try:
            while True:
                check_cancel(cancel)
                try:
                    code = process.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    if code:
        detail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise ValueError(f"FFmpeg no pudo terminar la exportación:\n{detail}")


def export_video(
    source: Path, destination: Path, settings: Settings,
    cancel: Event | None = None, progress: Progress | None = None,
    preserve_audio: bool = True,
) -> int:
    """Video MP4 H.264; procesa un fotograma a la vez y conserva audio como AAC.

    Se normaliza la salida a FPS constantes. Una fuente VFR puede perder la
    sincronización; esta limitación se documenta y se muestra en la interfaz.
    """
    _check_destination(source, destination)
    if destination.suffix.lower() != ".mp4":
        raise ValueError("Los videos se exportan en formato .mp4.")
    width, height, fps, expected = video_info(source)
    # H.264 yuv420p requiere tamaños pares; se añaden bordes en vez de recortar.
    out_width, out_height = width + width % 2, height + height % 2
    frames = 0
    with tempfile.TemporaryDirectory(prefix=".limpiacolor-", dir=destination.parent) as folder:
        temp = Path(folder)
        silent, completed = temp / "video.mp4", temp / "final.mp4"
        writer = imageio_ffmpeg.write_frames(
            str(silent), (out_width, out_height), fps=fps, codec="libx264", pix_fmt_in="rgb24",
            pix_fmt_out="yuv420p", quality=8, macro_block_size=1, ffmpeg_log_level="error",
            # imageio-ffmpeg redondea fps a dos decimales. El último -r de
            # entrada conserva frecuencias como 30000/1001 sin esa pérdida.
            input_params=["-r", format(fps, ".12g")],
        )
        capture = cv2.VideoCapture(str(source))
        try:
            writer.send(None)
            while True:
                check_cancel(cancel)
                ok, bgr = capture.read()
                if not ok:
                    break
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                cleaned, _ = process_frame(rgb, settings, cancel)
                if cleaned.shape[:2] != (height, width):
                    raise ValueError("El video cambia de resolución durante la reproducción.")
                if out_width != width or out_height != height:
                    cleaned = np.pad(cleaned, ((0, out_height - height), (0, out_width - width), (0, 0)), mode="edge")
                writer.send(np.ascontiguousarray(cleaned))
                frames += 1
                if progress is not None:
                    progress(frames, expected, "Procesando fotogramas")
        finally:
            capture.release()
            writer.close()
        check_cancel(cancel)
        if not frames:
            raise ValueError("No se pudo decodificar ningún fotograma.")
        if expected and frames < expected:
            raise ValueError(f"El video terminó antes de lo esperado ({frames} de {expected} fotogramas). No se guardó una salida incompleta.")
        if preserve_audio:
            if progress is not None:
                progress(frames, max(expected, frames), "Conservando audio")
            _run_ffmpeg([
                "-y", "-i", str(silent), "-i", str(source), "-map", "0:v:0", "-map", "1:a?",
                "-map_metadata", "1", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(completed),
            ], cancel, temp / "ffmpeg.log")
        else:
            _run_ffmpeg([
                "-y", "-i", str(silent), "-c", "copy", "-movflags", "+faststart", str(completed),
            ], cancel, temp / "ffmpeg.log")
        # Verifica la decodificación final antes de reemplazar el destino.
        verification = cv2.VideoCapture(str(completed))
        try:
            valid, _ = verification.read()
            if not valid:
                raise ValueError("El video exportado no pudo verificarse.")
            encoded_count = int(verification.get(cv2.CAP_PROP_FRAME_COUNT))
            if encoded_count != frames:
                raise ValueError(f"La salida contiene {encoded_count} fotogramas; se esperaban {frames}. No se guardó un archivo incompleto.")
        finally:
            verification.release()
        check_cancel(cancel)
        os.replace(completed, destination)
    return frames
