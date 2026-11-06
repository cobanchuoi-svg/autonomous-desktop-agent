from pathlib import Path

from agent.logistics.exporter import export_csv, preview_row
from agent.logistics.models import DocumentRecord, ExtractionField, FieldMapping, ImportTemplate
from agent.logistics.review import apply_correction
from agent.logistics.validation import validate_document


def sample_record() -> DocumentRecord:
    return DocumentRecord(
        document_id="doc-001",
        invoice_no=ExtractionField(original="INV-001", confidence=0.98, evidence_text="Invoice No: INV-001"),
        invoice_date=ExtractionField(original="2026-11-05", confidence=0.98, evidence_text="Date: 2026-11-05"),
        shipper=ExtractionField(original="ABC Company", confidence=0.90, evidence_text="Shipper: ABC Company"),
        currency=ExtractionField(original="USD", confidence=0.99, evidence_text="USD"),
        total_amount=ExtractionField(original="1250", confidence=0.99, evidence_text="Total USD 1250"),
    )


def sample_template() -> ImportTemplate:
    return ImportTemplate(
        target_system="test_erp",
        mappings=[
            FieldMapping(target_column="InvoiceNumber", source_field="invoice_no", required=True),
            FieldMapping(target_column="InvoiceDate", source_field="invoice_date", required=True, date_format="%d/%m/%Y"),
            FieldMapping(target_column="Amount", source_field="total_amount", required=True, decimal_places=2),
        ],
    )


def test_correction_preserves_original_value():
    record = sample_record()
    apply_correction(record, "shipper", "ABC-LOG")
    assert record.shipper.original == "ABC Company"
    assert record.shipper.value == "ABC-LOG"
    assert record.shipper.source == "user_correction"


def test_preview_maps_and_formats_customer_columns():
    row, issues = preview_row(sample_record(), sample_template())
    assert not issues
    assert row == {"InvoiceNumber": "INV-001", "InvoiceDate": "05/11/2026", "Amount": "1250.00"}


def test_export_refuses_invalid_data(tmp_path: Path):
    record = sample_record()
    record.invoice_date.final = "not-a-date"
    destination = tmp_path / "export.csv"
    issues = export_csv([record], sample_template(), destination)
    assert issues
    assert not destination.exists()
