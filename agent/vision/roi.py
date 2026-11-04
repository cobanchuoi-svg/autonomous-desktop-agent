"""Small, deterministic helpers for OCR regions of interest.

OCR backends operate in image-local coordinates.  These helpers retain the
screen offset so returned UI elements can always be clicked in desktop
coordinates after a crop.
"""

from dataclasses import dataclass
from typing import Iterable, Tuple

from PIL import Image

from agent.vision.parser import UIElement


@dataclass(frozen=True)
class ScreenRegion:
    """A clipped rectangle in desktop pixel coordinates."""

    left: int
    top: int
    right: int
    bottom: int

    def clipped(self, image: Image.Image) -> "ScreenRegion":
        left = max(0, min(self.left, image.width))
        top = max(0, min(self.top, image.height))
        right = max(left, min(self.right, image.width))
        bottom = max(top, min(self.bottom, image.height))
        return ScreenRegion(left, top, right, bottom)

    @property
    def size(self) -> Tuple[int, int]:
        return self.right - self.left, self.bottom - self.top


def crop_region(image: Image.Image, region: ScreenRegion) -> tuple[Image.Image, ScreenRegion]:
    """Return a safely clipped crop and the exact screen-space region used."""
    clipped = region.clipped(image)
    if clipped.right <= clipped.left or clipped.bottom <= clipped.top:
        raise ValueError("ROI must overlap the screenshot with positive width and height.")
    return image.crop((clipped.left, clipped.top, clipped.right, clipped.bottom)), clipped


def translate_elements(
    elements: Iterable[UIElement],
    region: ScreenRegion,
    *,
    surface: str = "foreground_window",
    container_id: str | None = None,
    window_title: str | None = None,
) -> list[UIElement]:
    """Convert OCR-local boxes back into screen-space coordinates."""
    translated: list[UIElement] = []
    for element in elements:
        x0, y0, x1, y1 = element.bbox
        translated.append(element.model_copy(update={
            "bbox": (x0 + region.left, y0 + region.top, x1 + region.left, y1 + region.top),
            "center_x": element.center_x + region.left,
            "center_y": element.center_y + region.top,
            "surface": surface,
            "container_id": container_id,
            "window_title": window_title,
        }))
    return translated
