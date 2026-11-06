"""Per-file deterministic structural analysis for the Brain reasoning layer."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from agent.brain.spatial_mapping import (
    BoundingBox,
    ScreenType,
    SpatialElement,
    cluster_rows,
    classify_screen,
    map_column_boundaries,
)


class DecisionStatus(str, Enum):
    PASS = "PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"


@dataclass(frozen=True)
class HeaderContext:
    name: str
    bbox: BoundingBox
    index: int
    confidence: float


@dataclass(frozen=True)
class ColumnContext:
    index: int
    header: str
    boundary: tuple[float, float]
    data_type: str
    pattern: str


@dataclass(frozen=True)
class RowContext:
    index: int
    y: float
    element_count: int
    values: tuple[str, ...]
    relative_geometry: Dict[str, float]


@dataclass
class StructuralAnalysisResult:
    status: DecisionStatus
    screen_type: ScreenType
    headers: List[HeaderContext] = field(default_factory=list)
    columns: List[ColumnContext] = field(default_factory=list)
    rows: List[RowContext] = field(default_factory=list)
    contexts: Dict[str, Any] = field(default_factory=dict)
    ai_required: bool = False
    review_reason: Optional[str] = None
    file_id: Optional[str] = None

    @property
    def decision(self) -> str:
        return self.status.value


def _as_spatial(element: Any) -> SpatialElement:
    if isinstance(element, SpatialElement):
        return element
    bbox = getattr(element, "bbox", None)
    text = getattr(element, "text", None)
    confidence = getattr(element, "confidence", 1.0)
    if isinstance(element, dict):
        bbox = element.get("bbox", bbox)
        text = element.get("text", text)
        confidence = element.get("confidence", confidence)
    return SpatialElement.from_bbox(str(text or ""), bbox, float(confidence))


def _infer_type(values: Sequence[str]) -> str:
    if not values:
        return "empty"
    numeric = sum(value.strip().replace(",", "").replace(".", "", 1).isdigit() for value in values)
    dates = sum(len(value.strip()) >= 8 and any(separator in value for separator in ("/", "-", ".")) for value in values)
    if numeric == len(values):
        return "number"
    if dates >= max(1, len(values) // 2):
        return "date_or_identifier"
    return "text"


def analyze_file_structure(
    elements: Sequence[Any],
    *,
    file_id: Optional[str] = None,
    expected_headers: Optional[Sequence[str]] = None,
    screen_type: Optional[ScreenType] = None,
) -> StructuralAnalysisResult:
    """Analyze one file independently; no context is retained between calls."""
    spatial = [_as_spatial(element) for element in elements]
    detected_type = screen_type or classify_screen(spatial)
    result = StructuralAnalysisResult(DecisionStatus.PASS, detected_type, file_id=file_id)
    rows = cluster_rows(spatial)
    if not rows:
        result.status = DecisionStatus.REVIEW_REQUIRED
        result.review_reason = "No OCR elements were detected"
        return result
    headers = sorted(rows[0], key=lambda item: item.bbox.center[0])
    result.headers = [HeaderContext(item.text.strip(), item.bbox, index, item.confidence) for index, item in enumerate(headers)]
    result.contexts["header"] = result.headers
    if any(not header.name or header.confidence < 0.60 for header in result.headers):
        result.status = DecisionStatus.REVIEW_REQUIRED
        result.review_reason = "Header text is missing or below the confidence threshold"
    boundaries, reason = map_column_boundaries(spatial, detected_type)
    if detected_type is ScreenType.DATA_SCREEN and not boundaries:
        result.status = DecisionStatus.REVIEW_REQUIRED
        result.review_reason = reason
    if expected_headers is not None:
        expected = [str(value).strip().lower() for value in expected_headers]
        actual = [header.name.lower() for header in result.headers]
        if actual != expected:
            result.status = DecisionStatus.SCHEMA_DRIFT
            result.review_reason = f"Expected headers {list(expected_headers)!r}, found {[header.name for header in result.headers]!r}"
    for index, header in enumerate(result.headers):
        values = [row[index].text for row in rows[1:] if len(row) > index]
        left, right = boundaries.get(index, (header.bbox.left, header.bbox.right))
        result.columns.append(ColumnContext(index, header.name, (left, right), _infer_type(values), "consistent" if values else "empty"))
    result.contexts["columns"] = result.columns
    header_y = headers[0].bbox.center[1]
    for row_index, row in enumerate(rows[1:]):
        ordered = sorted(row, key=lambda item: item.bbox.center[0])
        y = sum(item.bbox.center[1] for item in ordered) / len(ordered)
        result.rows.append(RowContext(row_index, y, len(ordered), tuple(item.text for item in ordered), {"delta_from_header": y - header_y, "column_count": float(len(ordered))}))
    result.contexts["rows"] = result.rows
    if detected_type is ScreenType.DATA_SCREEN and any(row.element_count != len(result.headers) for row in result.rows):
        result.status = DecisionStatus.REVIEW_REQUIRED
        result.review_reason = "Row structure does not match the detected column count"
    result.contexts["relative_geometry"] = {
        "header_to_first_row": result.rows[0].relative_geometry["delta_from_header"] if result.rows else 0.0,
        "row_count": len(result.rows),
    }
    return result


__all__ = ["DecisionStatus", "HeaderContext", "ColumnContext", "RowContext", "StructuralAnalysisResult", "analyze_file_structure"]
