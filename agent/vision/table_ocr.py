"""Deterministic conversion of positioned OCR words into table patches."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable, Optional

from agent.logistics.patch_context import PatchContext, PatchRowType, build_patch_context
from agent.logistics.schema import ApprovedSchema
from agent.vision.parser import UIElement


class TableOCRExtractor:
    """Build a structured patch from OCR elements and an approved schema."""

    def __init__(self, row_tolerance: int = 12, header_search_rows: int = 4):
        if row_tolerance < 1:
            raise ValueError("row_tolerance must be positive")
        self.row_tolerance = row_tolerance
        self.header_search_rows = header_search_rows

    def extract(
        self,
        elements: Iterable[UIElement],
        schema: ApprovedSchema,
        *,
        patch_id: str,
        source_region: Optional[str] = None,
    ) -> PatchContext:
        if not schema.is_approved:
            raise ValueError("Only an approved schema can extract a table patch")
        words = [element for element in elements if element.text.strip()]
        lines = _group_lines(words, self.row_tolerance)
        if not lines:
            raise ValueError("OCR returned no positioned text")

        header_index, centers = _find_header(lines, schema, self.header_search_rows)
        headers = [field.field_name for field in schema.fields]
        if header_index is None:
            return build_patch_context(
                patch_id=patch_id,
                headers=[],
                raw_rows=[],
                schema=schema,
                source_region=source_region,
            )

        raw_rows: list[list[Optional[str]]] = []
        row_types: list[PatchRowType] = []
        for line in lines[header_index + 1:]:
            values = _assign_to_columns(line, centers)
            if not any(value for value in values):
                continue
            row_type = _classify_row(values, schema)
            raw_rows.append(values)
            row_types.append(row_type)

        return build_patch_context(
            patch_id=patch_id,
            headers=headers,
            raw_rows=raw_rows,
            schema=schema,
            row_types=row_types,
            source_region=source_region,
        )


def _group_lines(elements: list[UIElement], tolerance: int) -> list[list[UIElement]]:
    lines: list[list[UIElement]] = []
    for element in sorted(elements, key=lambda item: (item.center_y, item.center_x)):
        target = next(
            (line for line in lines if abs(line[0].center_y - element.center_y) <= tolerance),
            None,
        )
        if target is None:
            lines.append([element])
        else:
            target.append(element)
    for line in lines:
        line.sort(key=lambda item: item.center_x)
    return lines


def _find_header(
    lines: list[list[UIElement]],
    schema: ApprovedSchema,
    search_rows: int,
) -> tuple[Optional[int], list[int]]:
    labels = {
        _normalize(field.field_name): index
        for index, field in enumerate(schema.fields)
    }
    labels.update({
        _normalize(field.semantic_role): index
        for index, field in enumerate(schema.fields)
        if field.semantic_role
    })
    best_index: Optional[int] = None
    best_matches: dict[int, UIElement] = {}
    for index, line in enumerate(lines[:max(1, search_rows)]):
        matches: dict[int, UIElement] = {}
        for element in line:
            field_index = labels.get(_normalize(element.text))
            if field_index is not None and field_index not in matches:
                matches[field_index] = element
        if len(matches) > len(best_matches):
            best_index, best_matches = index, matches
    if best_index is None or len(best_matches) != len(schema.fields):
        return None, []
    return best_index, [best_matches[index].center_x for index in range(len(schema.fields))]


def _assign_to_columns(line: list[UIElement], centers: list[int]) -> list[Optional[str]]:
    buckets: dict[int, list[str]] = defaultdict(list)
    for element in line:
        column = min(range(len(centers)), key=lambda index: abs(centers[index] - element.center_x))
        buckets[column].append(element.text.strip())
    return [
        " ".join(buckets[index]).strip() or None
        for index in range(len(centers))
    ]


def _classify_row(values: list[Optional[str]], schema: ApprovedSchema) -> PatchRowType:
    text = " ".join(value for value in values if value)
    lowered = text.lower()
    if lowered.startswith("total") or lowered == "subtotal":
        return "TOTAL_ROW"
    if any(re.fullmatch(r"[A-Z0-9]{2,3}(?:\s+[-:]?\s*.+)?", value or "") for value in values):
        if not any(re.fullmatch(r"\d{8,}", value or "") for value in values):
            return "AIRLINE_GROUP_ROW"
    return "DATA_ROW"


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
