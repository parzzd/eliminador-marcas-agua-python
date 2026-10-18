"""Coordenadas de imagen para zoom, desplazamiento y selección, sin depender de Tk."""

from dataclasses import dataclass
import math


@dataclass
class Viewport:
    image_width: int = 1
    image_height: int = 1
    width: int = 1
    height: int = 1
    zoom: float = 1.0
    center_x: float = 0.5
    center_y: float = 0.5

    @property
    def scale(self) -> float:
        return min(self.width / self.image_width, self.height / self.image_height) * self.zoom

    @property
    def offset(self) -> tuple[float, float]:
        return self.width / 2 - self.center_x * self.scale, self.height / 2 - self.center_y * self.scale

    def set_image(self, width: int, height: int, reset: bool = False) -> None:
        if (width, height) != (self.image_width, self.image_height) or reset:
            self.image_width, self.image_height = width, height
            self.fit()

    def resize(self, width: int, height: int) -> None:
        self.width, self.height = max(1, width), max(1, height)
        self._constrain()

    def fit(self) -> None:
        self.zoom = 1.0
        self.center_x, self.center_y = self.image_width / 2, self.image_height / 2

    def _constrain(self) -> None:
        half_width, half_height = self.width / (2 * self.scale), self.height / (2 * self.scale)
        self.center_x = self.image_width / 2 if half_width * 2 >= self.image_width else min(self.image_width - half_width, max(half_width, self.center_x))
        self.center_y = self.image_height / 2 if half_height * 2 >= self.image_height else min(self.image_height - half_height, max(half_height, self.center_y))

    def image_coordinates(self, x: float, y: float) -> tuple[float, float]:
        left, top = self.offset
        return (x - left) / self.scale, (y - top) / self.scale

    def image_point(self, x: float, y: float, clamp: bool = False) -> tuple[int, int] | None:
        px, py = self.image_coordinates(x, y)
        if clamp:
            return max(0, min(self.image_width - 1, math.floor(px))), max(0, min(self.image_height - 1, math.floor(py)))
        if 0 <= px < self.image_width and 0 <= py < self.image_height:
            return math.floor(px), math.floor(py)
        return None

    def canvas_point(self, x: float, y: float) -> tuple[float, float]:
        left, top = self.offset
        return left + x * self.scale, top + y * self.scale

    def zoom_at(self, value: float, x: float, y: float) -> None:
        px, py = self.image_coordinates(x, y)
        self.zoom = max(1.0, min(32.0, value))
        self.center_x = px + (self.width / 2 - x) / self.scale
        self.center_y = py + (self.height / 2 - y) / self.scale
        self._constrain()

    def pan(self, dx: float, dy: float) -> None:
        self.center_x -= dx / self.scale
        self.center_y -= dy / self.scale
        self._constrain()
