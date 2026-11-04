"""
Parsing and coordinate normalization for screen UI elements.
"""

from typing import List, Optional, Tuple
from pydantic import BaseModel, Field


class UIElement(BaseModel):
    """Represents a text or interactive element detected on screen."""
    text: str
    confidence: float = 1.0
    bbox: Tuple[int, int, int, int] = Field(
        ..., description="(x_min, y_min, x_max, y_max)"
    )
    center_x: int
    center_y: int
    element_id: Optional[str] = None
    control_type: Optional[str] = None
    source: str = "ocr"
    surface: str = "desktop"
    container_id: Optional[str] = None
    window_title: Optional[str] = None

    @classmethod
    def from_quad(
        cls,
        text: str,
        confidence: float,
        quad: List[List[float]],
        element_id: Optional[str] = None,
        control_type: Optional[str] = None,
        source: str = "ocr",
        surface: str = "desktop",
        container_id: Optional[str] = None,
        window_title: Optional[str] = None,
    ) -> "UIElement":
        """Build UIElement from 4-point polygon [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]."""
        xs = [pt[0] for pt in quad]
        ys = [pt[1] for pt in quad]
        x_min, x_max = int(min(xs)), int(max(xs))
        y_min, y_max = int(min(ys)), int(max(ys))
        center_x = (x_min + x_max) // 2
        center_y = (y_min + y_max) // 2
        return cls(
            text=text,
            confidence=confidence,
            bbox=(x_min, y_min, x_max, y_max),
            center_x=center_x,
            center_y=center_y,
            element_id=element_id,
            control_type=control_type,
            source=source,
            surface=surface,
            container_id=container_id,
            window_title=window_title,
        )


def find_elements_by_text(
    elements: List[UIElement],
    query: str,
    case_sensitive: bool = False,
    exact_match: bool = False,
) -> List[UIElement]:
    """Search detected UI elements by text content."""
    matches = []
    q = query if case_sensitive else query.lower()

    for el in elements:
        t = el.text if case_sensitive else el.text.lower()
        if exact_match:
            if t == q:
                matches.append(el)
        else:
            if q in t:
                matches.append(el)

    return matches
