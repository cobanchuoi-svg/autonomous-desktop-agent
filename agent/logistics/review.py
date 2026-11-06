"""Explicit human corrections; originals and evidence are never overwritten."""

from __future__ import annotations

from datetime import datetime, timezone

from agent.logistics.models import DocumentRecord, ExtractionField


def apply_correction(record: DocumentRecord, field_name: str, new_value: str) -> DocumentRecord:
    """Apply a reviewed correction and preserve the original extraction value."""
    field = getattr(record, field_name, None)
    if not isinstance(field, ExtractionField):
        raise KeyError(f"Unknown extractable field: {field_name}")
    value = new_value.strip()
    if not value:
        raise ValueError("Correction value cannot be blank")
    if field.original is None:
        field.original = field.final
    field.final = value
    field.source = "user_correction"
    field.confidence = 1.0
    field.corrected_at = datetime.now(timezone.utc)
    return record
