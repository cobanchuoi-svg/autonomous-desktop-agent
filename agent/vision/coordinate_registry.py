"""Current-frame object IDs and coordinates, kept separate from OCR and reasoning."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from agent.vision.parser import UIElement


@dataclass(frozen=True)
class CoordinateRecord:
    element_id: str
    bbox: Tuple[int, int, int, int]
    center: Tuple[int, int]
    screen_hash: str
    observed_at: datetime
    surface: str
    container_id: Optional[str]


class CoordinateRegistry:
    """Assigns opaque IDs and stores the coordinates valid for the latest screen frame."""

    def __init__(self) -> None:
        self._records: Dict[str, CoordinateRecord] = {}
        self._screen_hash = ""

    def update(self, elements: Iterable[UIElement], screen_hash: str) -> List[UIElement]:
        observed_at = datetime.now(timezone.utc)
        self._screen_hash = screen_hash
        self._records.clear()
        registered: List[UIElement] = []
        for index, element in enumerate(elements, start=1):
            element_id = f"obj_{screen_hash[:8]}_{index:03d}"
            record = CoordinateRecord(
                element_id=element_id,
                bbox=element.bbox,
                center=(element.center_x, element.center_y),
                screen_hash=screen_hash,
                observed_at=observed_at,
                surface=element.surface,
                container_id=element.container_id,
            )
            self._records[element_id] = record
            registered.append(element.model_copy(update={"element_id": element_id}))
        return registered

    def resolve(self, element_id: str, screen_hash: str) -> Optional[CoordinateRecord]:
        if screen_hash != self._screen_hash:
            return None
        record = self._records.get(element_id)
        if record is None or record.screen_hash != screen_hash:
            return None
        return record

    def snapshot(self) -> List[CoordinateRecord]:
        return list(self._records.values())
