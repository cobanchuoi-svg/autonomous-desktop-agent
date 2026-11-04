"""Current, timestamped view of the desktop assembled from perception output."""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from PIL import Image

from agent.vision.parser import UIElement
from agent.vision.coordinate_registry import CoordinateRegistry
from agent.vision.window_surface import WindowSurfaceDetector


@dataclass
class DesktopState:
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    screen_hash: str = ""
    screen_text: str = ""
    available_objects: List[UIElement] = field(default_factory=list)
    active_window: Optional[str] = None
    visible_popup: Optional[str] = None
    focused_element: Optional[UIElement] = None


class DesktopStateManager:
    """Build and retain the latest desktop snapshot; does not infer missing facts."""

    def __init__(self) -> None:
        self.current = DesktopState()
        self.coordinate_registry = CoordinateRegistry()
        self.window_surface_detector = WindowSurfaceDetector()

    def update(
        self,
        image: Image.Image,
        ocr_result: dict,
        accessible_elements: Optional[List[UIElement]] = None,
    ) -> DesktopState:
        pixels = image.convert("RGB").tobytes()
        accessible = list(accessible_elements or [])
        ocr_elements = list(ocr_result.get("elements", []))
        elements = []
        for index, element in enumerate(accessible):
            if not element.element_id:
                element = element.model_copy(update={"element_id": f"uia_{index}", "source": "uia"})
            elements.append(element)
        for index, element in enumerate(ocr_elements):
            duplicate = any(
                known.text.casefold() == element.text.casefold()
                and known.bbox[0] < element.bbox[2]
                and known.bbox[2] > element.bbox[0]
                and known.bbox[1] < element.bbox[3]
                and known.bbox[3] > element.bbox[1]
                for known in elements
            )
            if duplicate:
                continue
            if not element.element_id:
                element = element.model_copy(update={"element_id": f"ocr_{index}", "source": "ocr"})
            elements.append(element)
        screen_hash = hashlib.blake2b(pixels, digest_size=16).hexdigest()
        window = self.window_surface_detector.current()
        elements = self.window_surface_detector.tag_elements(elements, window)
        elements = self.coordinate_registry.update(elements, screen_hash)
        self.current = DesktopState(
            observed_at=datetime.now(timezone.utc),
            screen_hash=screen_hash,
            screen_text=ocr_result.get("full_text", ""),
            available_objects=elements,
            active_window=window.title if window else None,
            visible_popup=(window.title or window.window_id) if window and window.is_popup else None,
            focused_element=self.current.focused_element,
        )
        return self.current
