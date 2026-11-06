"""Three-sheet XLSX export for data, audit metadata, and approved schema."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from agent.logistics.audit import FieldAudit, ReviewEvent
from agent.logistics.models import DocumentRecord
from agent.logistics.schema import ApprovedSchema


def _cell_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def export_xlsx(
    records: Iterable[DocumentRecord],
    audits: Iterable[FieldAudit],
    schema: ApprovedSchema,
    destination: Path,
    review_events: Iterable[ReviewEvent] = (),
) -> None:
    """Export the minimum three sheets while preserving review metadata."""
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("XLSX export requires the optional 'openpyxl' package") from exc

    records = list(records)
    audits = list(audits)
    events = list(review_events)
    workbook = Workbook()
    data_sheet = workbook.active
    data_sheet.title = "Data"
    data_fields = [
        "document_id", "document_type", "bill_of_lading_no", "shipper", "consignee",
        "vessel", "port_of_loading", "port_of_discharge", "invoice_no", "invoice_date",
        "currency", "total_amount",
    ]
    data_sheet.append(data_fields)
    for record in records:
        data_sheet.append([record.document_id, record.document_type] + [
            record.get_value(name) or "" for name in data_fields[2:]
        ])

    audit_sheet = workbook.create_sheet("Audit")
    audit_fields = [
        "record_id", "field_name", "original_ocr_value", "suggested_value", "final_value",
        "validation_status", "ocr_confidence", "pattern_match_score", "confidence_score",
        "review_priority", "deduction_codes", "deduction_total", "validation_rules",
        "source_document", "source_page", "source_region", "potential_calculated_field",
        "calculation_reason", "reviewed_by", "reviewed_at", "review_comment",
    ]
    audit_sheet.append(audit_fields)
    for audit in audits:
        audit_sheet.append([
            _cell_value(getattr(audit, field))
            if field not in {"deduction_codes", "validation_rules"}
            else "; ".join(getattr(audit, field))
            for field in audit_fields
        ])
    for event in events:
        audit_sheet.append([
            event.record_id, event.field_name, event.original_ocr_value, event.suggested_value,
            event.final_value, event.decision, None, None, None, None, None, None, None,
            None, None, None, None, None, event.reviewed_by,
            _cell_value(event.reviewed_at), event.review_comment,
        ])

    schema_sheet = workbook.create_sheet("Schema")
    schema_sheet.append([
        "SchemaName", "SchemaVersion", "ApprovedByUser", "ApprovedAt", "FieldName",
        "SemanticRole", "FieldPriority", "DataType", "Pattern", "MinLength",
        "MaxLength", "DictionaryReference", "SequenceRule",
    ])
    for field in schema.fields:
        schema_sheet.append([
            schema.schema_name, schema.schema_version, schema.approved_by_user,
            _cell_value(schema.approved_at),
            field.field_name, field.semantic_role, field.field_priority, field.data_type,
            field.pattern, field.min_length, field.max_length, field.dictionary_reference,
            field.sequence_rule,
        ])

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
