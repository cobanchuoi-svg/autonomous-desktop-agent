"""Deterministic field scoring rules with explicit semantic profiles."""

from __future__ import annotations

import re
from typing import Iterable

from agent.logistics.audit import FieldAudit, ReviewPriority, ValidationFinding, ValidationStatus
from agent.logistics.models import ExtractionField
from agent.logistics.schema import ApprovedSchema, SchemaField


DEDUCTIONS = {
    "LOW_OCR_CONFIDENCE": 5,
    "LENGTH_MISMATCH": 10,
    "PARTIAL_PATTERN_MISMATCH": 15,
    "UNEXPECTED_CHARACTER": 20,
    "WRONG_DATA_TYPE": 30,
    "SCHEMA_DRIFT": 50,
}


def _status_for_score(score: int) -> tuple[ValidationStatus, ReviewPriority]:
    if score >= 95:
        return "PASS", "LOW"
    if score >= 80:
        return "WARNING", "MEDIUM"
    if score >= 50:
        return "REVIEW", "HIGH"
    return "ERROR", "CRITICAL"


def _finding(code: str, reason: str) -> ValidationFinding:
    return ValidationFinding(code=code, points=DEDUCTIONS[code], reason=reason)


def validate_field(
    record_id: str,
    field_name: str,
    value: ExtractionField,
    schema: ApprovedSchema,
    *,
    source_document: str | None = None,
    source_page: int | None = None,
    source_region: str | None = None,
) -> FieldAudit:
    """Score one extracted field without changing its OCR value."""
    if not schema.is_approved:
        raise ValueError("Only an approved schema can validate extracted data")
    field_schema = schema.field(field_name)
    original = value.original
    candidate = value.value
    findings: list[ValidationFinding] = []
    rules: list[str] = []

    if value.confidence < 0.70:
        findings.append(_finding("LOW_OCR_CONFIDENCE", "OCR confidence is below 70%"))
        rules.append("ocr_confidence >= 0.70")

    if candidate is None or not str(candidate).strip():
        findings.append(_finding("WRONG_DATA_TYPE", "Required value is empty"))
    else:
        text = str(candidate).strip()
        if field_schema.min_length is not None or field_schema.max_length is not None:
            rules.append("length")
            if field_schema.min_length is not None and len(text) < field_schema.min_length:
                findings.append(_finding("LENGTH_MISMATCH", "Value is shorter than schema minimum"))
            if field_schema.max_length is not None and len(text) > field_schema.max_length:
                findings.append(_finding("LENGTH_MISMATCH", "Value is longer than schema maximum"))

        if field_schema.data_type == "integer":
            rules.append("integer")
            if not re.fullmatch(r"[0-9]+", text):
                if re.search(r"[A-Za-z]", text):
                    findings.append(_finding("WRONG_DATA_TYPE", "Expected an integer but found alphabetic characters"))
                else:
                    findings.append(_finding("UNEXPECTED_CHARACTER", "Value contains non-numeric characters"))
        elif field_schema.data_type == "decimal":
            rules.append("decimal")
            if not re.fullmatch(r"-?[0-9]+(?:[.,][0-9]+)?", text):
                findings.append(_finding("WRONG_DATA_TYPE", "Expected a decimal value"))

        if field_schema.pattern:
            rules.append(f"pattern:{field_schema.pattern}")
            if not re.fullmatch(field_schema.pattern, text):
                if field_schema.data_type in {"integer", "decimal"} and re.search(r"[A-Za-z]", text):
                    findings.append(_finding(
                        "UNEXPECTED_CHARACTER",
                        "Numeric field contains an alphabetic or confusable character",
                    ))
                else:
                    findings.append(_finding("PARTIAL_PATTERN_MISMATCH", "Value does not match the approved field pattern"))

    if field_schema.field_priority == "required" and not candidate:
        findings.append(_finding("SCHEMA_DRIFT", "Required schema field is missing"))

    deduction_total = sum(item.points for item in findings)
    score = max(0, 100 - deduction_total)
    if any(item.code == "SCHEMA_DRIFT" for item in findings):
        score = min(score, 20)
    elif any(item.code == "WRONG_DATA_TYPE" for item in findings):
        score = min(score, 30)
    status, priority = _status_for_score(score)
    pattern_score = max(0, 100 - sum(
        item.points for item in findings
        if item.code in {"LENGTH_MISMATCH", "PARTIAL_PATTERN_MISMATCH", "UNEXPECTED_CHARACTER", "WRONG_DATA_TYPE", "SCHEMA_DRIFT"}
    ))
    return FieldAudit(
        record_id=record_id,
        field_name=field_name,
        original_ocr_value=original,
        suggested_value=value.final if value.final != original else None,
        final_value=value.value,
        validation_status=status,
        ocr_confidence=value.confidence,
        pattern_match_score=pattern_score,
        confidence_score=score,
        review_priority=priority,
        deduction_codes=[item.code for item in findings],
        deduction_total=deduction_total,
        validation_rules=rules,
        findings=findings,
        source_document=source_document,
        source_page=source_page,
        source_region=source_region,
    )


def validate_record(record, schema: ApprovedSchema, **source) -> list[FieldAudit]:
    """Validate all schema fields present on a normalized document record."""
    audits: list[FieldAudit] = []
    for field in schema.fields:
        try:
            extracted = getattr(record, field.field_name)
        except AttributeError:
            extracted = ExtractionField()
        audits.append(validate_field(record.document_id, field.field_name, extracted, schema, **source))
    return audits
