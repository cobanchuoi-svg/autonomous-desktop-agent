"""Deterministic validation before a record can be exported for import."""

from __future__ import annotations

from datetime import date
from typing import Iterable

from agent.logistics.models import DocumentRecord, normalize_decimal


def validate_document(record: DocumentRecord, required_fields: Iterable[str] = ()) -> list[str]:
    """Return human-readable issues; an empty list means the checks passed."""
    issues: list[str] = []
    for field_name in required_fields:
        try:
            value = record.get_value(field_name)
        except KeyError:
            issues.append(f"Unknown required field in template: {field_name}")
            continue
        if not value:
            issues.append(f"Missing required field: {field_name}")

    date_value = record.invoice_date.value
    if date_value:
        try:
            date.fromisoformat(date_value)
        except ValueError:
            issues.append("invoice_date must use ISO format YYYY-MM-DD before export")

    amount_value = record.total_amount.value
    if amount_value:
        try:
            if float(normalize_decimal(amount_value) or "0") < 0:
                issues.append("total_amount cannot be negative")
        except ValueError:
            issues.append("total_amount is not a valid decimal")

    if amount_value and not record.currency.value:
        issues.append("currency is required when total_amount is present")

    low_confidence = [
        name for name in ("invoice_no", "invoice_date", "currency", "total_amount")
        if getattr(record, name).value and getattr(record, name).confidence < 0.70
    ]
    if low_confidence:
        issues.append("Review low-confidence fields: " + ", ".join(low_confidence))
    return issues
