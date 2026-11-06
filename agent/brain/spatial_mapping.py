"""Deterministic spatial reasoning primitives used by Brain structural analysis."""

from dataclasses import dataclass, field
from enum import Enum
from math import atan2, degrees, hypot
from statistics import median
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


class ScreenType(str, Enum):
    DATA_SCREEN = "DATA_SCREEN"
    FORM_SCREEN = "FORM_SCREEN"
    TEXT_SCREEN = "TEXT_SCREEN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BoundingBox:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        if self.right < self.left or self.bottom < self.top:
            raise ValueError("BoundingBox coordinates must be ordered")

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)

    def intersects(self, other: "BoundingBox") -> bool:
        return (
            min(self.right, other.right) > max(self.left, other.left)
            and min(self.bottom, other.bottom) > max(self.top, other.top)
        )

    def distance_to(self, other: "BoundingBox") -> float:
        x1, y1 = self.center
        x2, y2 = other.center
        return hypot(x2 - x1, y2 - y1)

    def angle_to(self, other: "BoundingBox") -> float:
        x1, y1 = self.center
        x2, y2 = other.center
        return degrees(atan2(y2 - y1, x2 - x1))


@dataclass(frozen=True)
class SpatialElement:
    text: str
    bbox: BoundingBox
    confidence: float = 1.0
    role: Optional[str] = None
    context_id: Optional[str] = None
    source: str = "ocr"

    @classmethod
    def from_bbox(
        cls,
        text: str,
        bbox: Sequence[float],
        confidence: float = 1.0,
        **kwargs: object,
    ) -> "SpatialElement":
        if len(bbox) != 4:
            raise ValueError("bbox must contain left, top, right, bottom")
        return cls(text, BoundingBox(*map(float, bbox)), confidence, **kwargs)


class MappingStatus(str, Enum):
    MAPPED = "MAPPED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True)
class LabelValuePair:
    label: SpatialElement
    value: SpatialElement
    distance: float


@dataclass
class MappingResult:
    status: MappingStatus
    mappings: List[LabelValuePair] = field(default_factory=list)
    reason: str = ""


def _row_tolerance(elements: Sequence[SpatialElement]) -> float:
    heights = [element.bbox.height for element in elements if element.bbox.height > 0]
    return max(4.0, (median(heights) if heights else 12.0) * 0.75)


def cluster_rows(elements: Iterable[SpatialElement]) -> List[List[SpatialElement]]:
    rows: List[List[SpatialElement]] = []
    ordered = sorted(elements, key=lambda item: (item.bbox.center[1], item.bbox.center[0]))
    tolerance = _row_tolerance(ordered)
    for element in ordered:
        row = next(
            (candidate for candidate in rows if abs(candidate[0].bbox.center[1] - element.bbox.center[1]) <= tolerance),
            None,
        )
        if row is None:
            rows.append([element])
        else:
            row.append(element)
            row.sort(key=lambda item: item.bbox.center[0])
    return sorted(rows, key=lambda row: row[0].bbox.center[1])


def classify_screen(elements: Sequence[SpatialElement]) -> ScreenType:
    rows = cluster_rows(elements)
    if not elements:
        return ScreenType.UNKNOWN
    if len(rows) >= 2 and len(rows[0]) >= 2:
        repeated = sum(len(row) == len(rows[0]) for row in rows[1:])
        if repeated >= max(1, len(rows[1:]) // 2):
            return ScreenType.DATA_SCREEN
    if any(element.text.rstrip().endswith(":") for element in elements) or len(rows) >= 2:
        return ScreenType.FORM_SCREEN
    return ScreenType.TEXT_SCREEN


def map_label_values(
    labels: Sequence[SpatialElement],
    values: Sequence[SpatialElement],
    *,
    angle_tolerance: float = 15.0,
    max_distance: Optional[float] = None,
) -> MappingResult:
    if not labels or not values:
        return MappingResult(MappingStatus.NOT_FOUND, reason="No labels or values were supplied")
    tolerance = _row_tolerance([*labels, *values])
    limit = max_distance if max_distance is not None else max(200.0, tolerance * 12)
    mappings: List[LabelValuePair] = []
    used: set[int] = set()
    for label in labels:
        candidates: List[Tuple[float, int, SpatialElement]] = []
        for index, value in enumerate(values):
            if index in used or label.context_id != value.context_id:
                continue
            lx, _ = label.bbox.center
            vx, _ = value.bbox.center
            if vx <= lx or abs(label.bbox.center[1] - value.bbox.center[1]) > tolerance:
                continue
            if abs(label.bbox.angle_to(value.bbox)) > angle_tolerance or label.bbox.intersects(value.bbox):
                continue
            distance = label.bbox.distance_to(value.bbox)
            if distance <= limit:
                candidates.append((distance, index, value))
        if len(candidates) != 1:
            return MappingResult(
                MappingStatus.REVIEW_REQUIRED,
                mappings,
                f"Label '{label.text}' has {len(candidates)} valid value candidates; mapping is ambiguous",
            )
        distance, index, value = candidates[0]
        used.add(index)
        mappings.append(LabelValuePair(label, value, distance))
    return MappingResult(MappingStatus.MAPPED, mappings, "All labels mapped deterministically")


def map_column_boundaries(
    elements: Sequence[SpatialElement],
    screen_type: ScreenType,
) -> Tuple[Dict[int, Tuple[float, float]], str]:
    if screen_type is not ScreenType.DATA_SCREEN:
        return {}, "Column boundaries are only valid for DATA_SCREEN"
    rows = cluster_rows(elements)
    if not rows or len(rows[0]) < 2:
        return {}, "No stable header row with multiple columns"
    headers = sorted(rows[0], key=lambda item: item.bbox.center[0])
    boundaries: Dict[int, Tuple[float, float]] = {}
    for index, header in enumerate(headers):
        left = header.bbox.left if index == 0 else (headers[index - 1].bbox.center[0] + header.bbox.center[0]) / 2
        right = header.bbox.right if index == len(headers) - 1 else (header.bbox.center[0] + headers[index + 1].bbox.center[0]) / 2
        if right <= left:
            return {}, "Column boundaries overlap or are not ordered"
        boundaries[index] = (left, right)
    return boundaries, "Column boundaries inferred from current-file header geometry"


__all__ = [
    "BoundingBox",
    "SpatialElement",
    "ScreenType",
    "MappingStatus",
    "LabelValuePair",
    "MappingResult",
    "cluster_rows",
    "classify_screen",
    "map_label_values",
    "map_column_boundaries",
]
