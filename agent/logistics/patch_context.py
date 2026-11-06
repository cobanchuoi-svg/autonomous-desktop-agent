"""Structured table patches and column-specific context validation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from agent.logistics.models import ExtractionField
from agent.logistics.schema import ApprovedSchema


PatchRowType = Literal[
    "HEADER_ROW",
    "AIRLINE_GROUP_ROW",
    "DATA_ROW",
    "TOTAL_ROW",
    "UNKNOWN_ROW",
]


class HeaderContext(BaseModel):
    """The approved/observed header layout for one table patch."""

    names: list[str]
    normalized_names: list[str]
    fingerprint: str

    @classmethod
    def from_names(cls, names: Sequence[str]) -> "HeaderContext":
        cleaned = [str(name).strip() for name in names]
        normalized = [_normalize_header(name) for name in cleaned]
        return cls(
            names=cleaned,
            normalized_names=normalized,
            fingerprint=_fingerprint(normalized),
        )


class ColumnContext(BaseModel):
    """Rules and evidence belonging to one column only."""

    field_name: str
    header_name: str
    normalized_header: str
    position: int = Field(ge=0)
    data_type: str
    pattern: Optional[str] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    semantic_role: str
    observed_examples: list[str] = Field(default_factory=list)
    context_fingerprint: str

    @classmethod
    def from_schema(
        cls,
        position: int,
        header_name: str,
        field_name: str,
        schema: ApprovedSchema,
        observed_values: Sequence[str] = (),
    ) -> "ColumnContext":
        field = schema.field(field_name)
        examples = list(dict.fromkeys(
            value.strip() for value in observed_values if value and value.strip()
        ))[:5]
        normalized_header = _normalize_header(header_name)
        fingerprint = _fingerprint([
            field_name,
            normalized_header,
            str(position),
            field.data_type,
            field.pattern or "",
            field.semantic_role,
        ])
        return cls(
            field_name=field_name,
            header_name=header_name,
            normalized_header=normalized_header,
            position=position,
            data_type=field.data_type,
            pattern=field.pattern,
            min_length=field.min_length,
            max_length=field.max_length,
            semantic_role=field.semantic_role,
            observed_examples=examples,
            context_fingerprint=fingerprint,
        )


class GroupContext(BaseModel):
    """Context created by a group row; never silently fills missing cells."""

    group_context_id: str
    airline_code: Optional[str] = None
    airline_name: Optional[str] = None
    source_row_key: Optional[str] = None
    pattern_id: Optional[str] = None


class PatchRow(BaseModel):
    row_key: str
    row_type: PatchRowType = "UNKNOWN_ROW"
    cells: dict[str, ExtractionField] = Field(default_factory=dict)
    source_region: Optional[str] = None
    group_context_id: Optional[str] = None
    complete_structure: bool = True
    missing_columns: list[str] = Field(default_factory=list)


class PatchContext(BaseModel):
    """A complete visible table region, including all columns and rows."""

    patch_id: str
    header: HeaderContext
    columns: list[ColumnContext]
    rows: list[PatchRow]
    source_region: Optional[str] = None
    schema_version: str
    group_context: Optional[GroupContext] = None
    completeness_status: Literal["COMPLETE", "INCOMPLETE_PATCH", "SCHEMA_DRIFT"] = "COMPLETE"

    @property
    def field_names(self) -> list[str]:
        return [column.field_name for column in self.columns]


def build_patch_context(
    *,
    patch_id: str,
    headers: Sequence[str],
    raw_rows: Sequence[Sequence[Optional[str]]],
    schema: ApprovedSchema,
    row_types: Optional[Sequence[PatchRowType]] = None,
    source_region: Optional[str] = None,
    group_context: Optional[GroupContext] = None,
) -> PatchContext:
    """Build a patch without inventing values for missing cells."""
    if not schema.is_approved:
        raise ValueError("Only an approved schema can build a patch context")
    if len(headers) != len(schema.fields):
        return PatchContext(
            patch_id=patch_id,
            header=HeaderContext.from_names(headers),
            columns=[],
            rows=[],
            source_region=source_region,
            schema_version=schema.schema_version,
            group_context=group_context,
            completeness_status="SCHEMA_DRIFT",
        )

    header = HeaderContext.from_names(headers)
    columns = [
        ColumnContext.from_schema(
            position=index,
            header_name=headers[index],
            field_name=field.field_name,
            schema=schema,
            observed_values=[
                str(row[index]) for row in raw_rows
                if len(row) > index and row[index] is not None
            ],
        )
        for index, field in enumerate(schema.fields)
    ]
    rows: list[PatchRow] = []
    for row_index, raw_row in enumerate(raw_rows):
        missing = [
            field.field_name
            for index, field in enumerate(schema.fields)
            if index >= len(raw_row) or raw_row[index] is None
        ]
        cells = {
            field.field_name: ExtractionField(
                original=None if index >= len(raw_row) else raw_row[index],
                confidence=0.0 if index >= len(raw_row) or raw_row[index] is None else 1.0,
            )
            for index, field in enumerate(schema.fields)
        }
        row_key = make_row_key(cells, group_context)
        rows.append(PatchRow(
            row_key=row_key,
            row_type=row_types[row_index] if row_types and row_index < len(row_types) else "UNKNOWN_ROW",
            cells=cells,
            source_region=source_region,
            group_context_id=group_context.group_context_id if group_context else None,
            complete_structure=not missing,
            missing_columns=missing,
        ))

    return PatchContext(
        patch_id=patch_id,
        header=header,
        columns=columns,
        rows=rows,
        source_region=source_region,
        schema_version=schema.schema_version,
        group_context=group_context,
        completeness_status="INCOMPLETE_PATCH" if any(
            not row.complete_structure and row.row_type not in {"AIRLINE_GROUP_ROW", "TOTAL_ROW"}
            for row in rows
        ) else "COMPLETE",
    )


def compare_patch_structure(previous: PatchContext, current: PatchContext) -> list[str]:
    """Return explicit structural differences; values are not compared here."""
    differences: list[str] = []
    if previous.schema_version != current.schema_version:
        differences.append("SCHEMA_VERSION_CHANGED")
    if previous.header.fingerprint != current.header.fingerprint:
        differences.append("HEADER_CHANGED")
    previous_columns = [
        (column.field_name, column.normalized_header, column.position, column.data_type)
        for column in previous.columns
    ]
    current_columns = [
        (column.field_name, column.normalized_header, column.position, column.data_type)
        for column in current.columns
    ]
    if previous_columns != current_columns:
        differences.append("COLUMN_STRUCTURE_CHANGED")
    if len(previous.columns) != len(current.columns):
        differences.append("COLUMN_COUNT_CHANGED")
    return list(dict.fromkeys(differences))


def make_row_key(
    cells: Mapping[str, ExtractionField],
    group_context: Optional[GroupContext] = None,
) -> str:
    """Create a stable key from extracted anchors, not screen coordinates."""
    values = {
        name: field.value.strip() if field.value else ""
        for name, field in sorted(cells.items())
    }
    if group_context:
        values["_group"] = group_context.group_context_id
    return _fingerprint([json.dumps(values, sort_keys=True, ensure_ascii=False)])


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _fingerprint(values: Sequence[str]) -> str:
    payload = "\x1f".join(values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
