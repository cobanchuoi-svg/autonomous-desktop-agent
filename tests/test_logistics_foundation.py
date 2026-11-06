import json
from pathlib import Path

from agent.logistics.audit import ReviewEvent
from agent.logistics.models import DocumentRecord, ExtractionField
from agent.logistics.recovery import JobProgress, ProgressStore, RecoveryEvent
from agent.logistics.rules import validate_field
from agent.logistics.schema import ApprovedSchema, SchemaField
from agent.logistics.patch_context import (
    GroupContext,
    build_patch_context,
    compare_patch_structure,
)
from agent.logistics.short_term_memory import RollingPatchMemory
from agent.logistics.xlsx_exporter import export_xlsx


def schema() -> ApprovedSchema:
    return ApprovedSchema(
        schema_name="mawb",
        schema_version="1.0",
        fields=[
            SchemaField(
                field_name="invoice_no",
                semantic_role="MAWB",
                field_priority="required",
                data_type="text",
                pattern=r"[0-9]{11,12}",
                min_length=11,
                max_length=12,
            ),
            SchemaField(
                field_name="currency",
                semantic_role="airline_code",
                data_type="text",
                pattern=r"[A-Z0-9]{2,3}",
            ),
        ],
    ).approve("tester")


def test_scoring_uses_approved_semantic_schema_without_mutating_value():
    approved = schema()
    field = ExtractionField(original="9I017675825", confidence=0.98)
    audit = validate_field("r1", "invoice_no", field, approved)
    assert audit.final_value == "9I017675825"
    assert audit.validation_status == "WARNING"
    assert "PARTIAL_PATTERN_MISMATCH" in audit.deduction_codes

    airline = validate_field("r1", "currency", ExtractionField(original="WY", confidence=0.98), approved)
    assert airline.validation_status == "PASS"


def test_progress_store_round_trip_and_recovery_event(tmp_path: Path):
    store = ProgressStore(tmp_path / "progress.json")
    progress = JobProgress(job_id="JOB-001", schema_version="1.0")
    progress.mark_batch_success(2, ["a", "b"], ["b"], scroll_iteration=3)
    store.save(progress)
    loaded = store.load()
    assert loaded is not None
    assert loaded.rows_processed == 2
    assert loaded.processed_record_ids == ["a", "b"]
    store.append_recovery_event(RecoveryEvent(job_id="JOB-001", recovery_reason="agent_crash"))
    assert "agent_crash" in (tmp_path / "recovery_events.jsonl").read_text(encoding="utf-8")


def test_export_xlsx_has_data_audit_and_schema_sheets(tmp_path: Path):
    record = DocumentRecord(
        document_id="r1",
        invoice_no=ExtractionField(original="91017675825", confidence=0.99),
        currency=ExtractionField(original="WY", confidence=0.99),
    )
    approved = schema()
    audits = [
        validate_field("r1", "invoice_no", record.invoice_no, approved),
        validate_field("r1", "currency", record.currency, approved),
    ]
    target = tmp_path / "result.xlsx"
    export_xlsx(
        [record],
        audits,
        approved,
        target,
        [ReviewEvent(
            record_id="r1", field_name="invoice_no", decision="APPROVED",
            original_ocr_value="91017675825", final_value="91017675825", reviewed_by="tester",
        )],
    )
    from openpyxl import load_workbook
    workbook = load_workbook(target)
    assert workbook.sheetnames == ["Data", "Audit", "Schema"]
    assert workbook["Data"]["I2"].value == "91017675825"
    assert workbook["Audit"]["F2"].value == "PASS"
    assert workbook["Schema"]["E2"].value == "invoice_no"


def test_patch_builds_context_for_each_column_and_keeps_missing_cells():
    approved = schema()
    patch = build_patch_context(
        patch_id="patch-1",
        headers=["MAWB", "Airline"],
        raw_rows=[
            ["91017675825", "WY"],
            ["91017676551", None],
        ],
        schema=approved,
        source_region="page1:R1:R3",
    )

    assert [column.field_name for column in patch.columns] == ["invoice_no", "currency"]
    assert patch.columns[0].header_name == "MAWB"
    assert patch.columns[1].semantic_role == "airline_code"
    assert patch.completeness_status == "INCOMPLETE_PATCH"
    assert patch.rows[1].missing_columns == ["currency"]
    assert patch.rows[1].cells["currency"].value is None


def test_patch_structure_detects_header_and_column_changes():
    approved = schema()
    first = build_patch_context(
        patch_id="patch-1",
        headers=["MAWB", "Airline"],
        raw_rows=[["91017675825", "WY"]],
        schema=approved,
    )
    changed = build_patch_context(
        patch_id="patch-2",
        headers=["Airline", "MAWB"],
        raw_rows=[["WY", "91017675825"]],
        schema=approved,
    )

    differences = compare_patch_structure(first, changed)
    assert "HEADER_CHANGED" in differences
    assert "COLUMN_STRUCTURE_CHANGED" in differences


def test_rolling_memory_deduplicates_overlap_and_keeps_processed_index():
    approved = schema()
    first = build_patch_context(
        patch_id="patch-1",
        headers=["MAWB", "Airline"],
        raw_rows=[
            ["91017675825", "WY"],
            ["91017676551", "WY"],
            ["91017811954", "WY"],
        ],
        schema=approved,
        group_context=GroupContext(
            group_context_id="group-1",
            airline_code="WY",
        ),
    )
    second = build_patch_context(
        patch_id="patch-2",
        headers=["MAWB", "Airline"],
        raw_rows=[
            ["91017676551", "WY"],
            ["91017811954", "WY"],
            ["91017900000", "WY"],
        ],
        schema=approved,
        group_context=first.group_context,
    )

    memory = RollingPatchMemory(overlap_size=2)
    memory.commit(first, first.rows)
    assert len(memory.merge_with_overlap(second)) == 3
    assert len(memory.prepare(second)) == 1
    memory.commit(second, memory.prepare(second))
    assert len(memory.state.retained_overlap) == 2
    assert len(memory.state.processed_row_keys) == 4
