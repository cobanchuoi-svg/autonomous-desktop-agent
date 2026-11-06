"""Export normalized, reviewed records into an approved customer CSV template."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Iterable

from agent.logistics.models import DocumentRecord, ImportTemplate, normalize_decimal
from agent.logistics.validation import validate_document


def preview_row(record: DocumentRecord, template: ImportTemplate) -> tuple[dict[str, str], list[str]]:
    """Build a target-system row without writing an import file yet."""
    required = [item.source_field for item in template.mappings if item.required]
    issues = validate_document(record, required)
    row: dict[str, str] = {}
    for mapping in template.mappings:
        try:
            value = record.get_value(mapping.source_field)
        except KeyError:
            issues.append(f"Mapping references unsupported source field: {mapping.source_field}")
            value = None
        if value and mapping.date_format:
            try:
                value = date.fromisoformat(value).strftime(mapping.date_format)
            except ValueError:
                issues.append(f"Could not format {mapping.source_field} as a date")
        if value and mapping.decimal_places is not None:
            try:
                value = normalize_decimal(value, mapping.decimal_places)
            except ValueError:
                issues.append(f"Could not format {mapping.source_field} as a decimal")
        row[mapping.target_column] = value or ""
    return row, sorted(set(issues))


def export_csv(records: Iterable[DocumentRecord], template: ImportTemplate, destination: Path) -> list[str]:
    """Write only validated reviewed data. Returns validation issues if blocked."""
    rows: list[dict[str, str]] = []
    issues: list[str] = []
    for record in records:
        row, record_issues = preview_row(record, template)
        if record_issues:
            issues.extend(f"{record.document_id}: {item}" for item in record_issues)
        else:
            rows.append(row)
    if issues:
        return issues
    headers = [item.target_column for item in template.mappings]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding=template.encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter=template.delimiter)
        writer.writeheader()
        writer.writerows(rows)
    return []
