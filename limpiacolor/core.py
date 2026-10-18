"""Procesamiento independiente de la interfaz. Todos los colores usan RGB uint8."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event

import cv2
import numpy as np


class ProcessingCancelled(Exception):
    """El usuario canceló el procesamiento."""


def check_cancel(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ProcessingCancelled("Proceso cancelado.")


@dataclass(frozen=True)
class ColorTarget:
    rgb: tuple[int, int, int]
    tolerance: int = 36

    def __post_init__(self) -> None:
        if len(self.rgb) != 3 or any(not 0 <= c <= 255 for c in self.rgb):
            raise ValueError("El color debe tener tres valores RGB entre 0 y 255.")
        if not 0 <= self.tolerance <= 255:
            raise ValueError("La tolerancia debe estar entre 0 y 255.")

    @property
    def hex(self) -> str:
        return "#%02X%02X%02X" % self.rgb


@dataclass(frozen=True)
class Settings:
    colors: tuple[ColorTarget, ...] = field(default_factory=tuple)
    method: str = "dominant"
    radius: int = 3
    expansion: int = 1
    # Coordenadas de la imagen original: izquierda, arriba, derecha y abajo (exclusivas).
    roi: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if self.method not in {"dominant", "maximum", "telea"}:
            raise ValueError("Método de relleno desconocido.")
        if not 1 <= self.radius <= 15 or not 0 <= self.expansion <= 15:
            raise ValueError("Radio o expansión fuera de rango.")


def validate_image(image: np.ndarray) -> None:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Se esperaba una imagen RGB uint8 de tres canales.")
    if not image.size:
        raise ValueError("La imagen está vacía.")


def make_mask(image: np.ndarray, settings: Settings) -> np.ndarray:
    """Unión multicolor por distancia euclídea RGB; limita también la expansión a la ROI."""
    validate_image(image)
    height, width = image.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    x0, y0, x1, y1 = 0, 0, width, height
    if settings.roi is not None:
        left, top, right, bottom = settings.roi
        x0, y0 = max(0, left), max(0, top)
        x1, y1 = min(width, right), min(height, bottom)
    if x0 >= x1 or y0 >= y1 or not settings.colors:
        return mask
    # float32 evita overflow al elevar al cuadrado diferencias de 255.
    source = image[y0:y1, x0:x1].astype(np.float32)
    selected = np.zeros(source.shape[:2], dtype=bool)
    for color in settings.colors:
        difference = source - np.asarray(color.rgb, dtype=np.float32)
        selected |= np.einsum("ijk,ijk->ij", difference, difference) <= color.tolerance**2
    local_mask = selected.astype(np.uint8) * 255
    if settings.expansion:
        side = 2 * settings.expansion + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (side, side))
        local_mask = cv2.dilate(local_mask, kernel)
    mask[y0:y1, x0:x1] = local_mask
    return mask


def _dominant_values(
    padded: np.ndarray, known: np.ndarray, ys: np.ndarray, xs: np.ndarray, radius: int
) -> np.ndarray:
    """Moda RGB local agrupada en intervalos de 16; promedio del grupo ganador.

    Los grupos evitan que el ruido de compresión vuelva únicos todos los vecinos.
    Procesa pequeños lotes para limitar la memoria independientemente de la resolución.
    """
    delta = np.arange(-radius, radius + 1)
    oy, ox = np.meshgrid(delta, delta, indexing="ij")
    yy = ys[:, None] + radius + oy.ravel()
    xx = xs[:, None] + radius + ox.ravel()
    neighbors = padded[yy, xx]
    valid = known[yy, xx]
    quantized = neighbors.astype(np.int32) // 16
    keys = quantized[..., 0] * 256 + quantized[..., 1] * 16 + quantized[..., 2]
    # El contenedor 4096 representa vecinos desconocidos, excluidos de la moda.
    keys = np.where(valid, keys, 4096)
    offsets = np.arange(len(ys), dtype=np.int32)[:, None] * 4097
    counts = np.bincount((keys + offsets).ravel(), minlength=len(ys) * 4097)
    winners = counts.reshape(len(ys), 4097)[:, :4096].argmax(axis=1)
    chosen = valid & (keys == winners[:, None])
    totals = (neighbors.astype(np.float32) * chosen[..., None]).sum(axis=1)
    return np.rint(totals / chosen.sum(axis=1, keepdims=True)).astype(np.uint8)


def fill_neighbors(
    image: np.ndarray, mask: np.ndarray, radius: int, method: str, cancel: Event | None = None
) -> np.ndarray:
    """Rellena desde el borde hacia el centro, excluyendo los píxeles enmascarados.

    dominant: color de mayor frecuencia local. maximum: máximo por canal RGB.
    Ambos propagan vecinos válidos cuando la máscara supera el radio seleccionado.
    """
    result = image.copy()
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return result
    if len(ys) == mask.size:
        raise ValueError("La máscara cubre toda la imagen. Reduce la tolerancia o selecciona una zona.")
    # Recortar acelera las marcas pequeñas sin modificar el contexto necesario.
    y0, y1 = max(0, int(ys.min()) - radius), min(image.shape[0], int(ys.max()) + radius + 1)
    x0, x1 = max(0, int(xs.min()) - radius), min(image.shape[1], int(xs.max()) + radius + 1)
    work = result[y0:y1, x0:x1].copy()
    unknown = mask[y0:y1, x0:x1] != 0
    known = ~unknown
    work[unknown] = 0
    kernel = np.ones((radius * 2 + 1, radius * 2 + 1), dtype=np.uint8)
    while np.any(unknown):
        check_cancel(cancel)
        frontier = unknown & (cv2.dilate(known.astype(np.uint8), kernel) != 0)
        rows, columns = np.nonzero(frontier)
        if not len(rows):
            raise ValueError("No hay vecinos disponibles para rellenar la máscara.")
        if method == "maximum":
            candidates = cv2.dilate(work, kernel)
            work[frontier] = candidates[frontier]
        else:
            padded_image = np.pad(work, ((radius, radius), (radius, radius), (0, 0)))
            padded_known = np.pad(known, radius, constant_values=False)
            for start in range(0, len(rows), 128):
                check_cancel(cancel)
                batch_y, batch_x = rows[start : start + 128], columns[start : start + 128]
                work[batch_y, batch_x] = _dominant_values(
                    padded_image, padded_known, batch_y, batch_x, radius
                )
        known[frontier] = True
        unknown[frontier] = False
    selected = mask[y0:y1, x0:x1] != 0
    result[y0:y1, x0:x1][selected] = work[selected]
    return result


def process_frame(
    image: np.ndarray, settings: Settings, cancel: Event | None = None
) -> tuple[np.ndarray, np.ndarray]:
    check_cancel(cancel)
    mask = make_mask(image, settings)
    if not np.any(mask):
        return image.copy(), mask
    if np.all(mask):
        raise ValueError("La máscara cubre toda la imagen. Reduce la tolerancia o selecciona una zona.")
    if settings.method == "telea":
        result = cv2.inpaint(image, mask, float(settings.radius), cv2.INPAINT_TELEA)
    else:
        result = fill_neighbors(image, mask, settings.radius, settings.method, cancel)
    check_cancel(cancel)
    return result, mask


def mask_overlay(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    result = image.copy()
    selected = mask != 0
    result[selected] = (image[selected].astype(np.float32) * 0.35 + np.array([255, 70, 114]) * 0.65).astype(np.uint8)
    return result
