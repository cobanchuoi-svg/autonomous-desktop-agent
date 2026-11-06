from agent.logistics.schema import ApprovedSchema, SchemaField
from agent.vision.parser import UIElement
from agent.vision.table_ocr import TableOCRExtractor


def approved_table_schema() -> ApprovedSchema:
    return ApprovedSchema(
        schema_name="table",
        schema_version="1.0",
        fields=[
            SchemaField(field_name="stt", semantic_role="STT", data_type="integer"),
            SchemaField(field_name="mawb", semantic_role="MAWB", data_type="text"),
            SchemaField(field_name="airline", semantic_role="Airline", data_type="text"),
        ],
    ).approve("tester")


def element(text: str, x: int, y: int) -> UIElement:
    return UIElement(
        text=text,
        confidence=0.99,
        bbox=(x, y, x + 20, y + 10),
        center_x=x,
        center_y=y,
    )


def test_table_ocr_uses_header_positions_for_each_column():
    elements = [
        element("STT", 10, 10), element("MAWB", 110, 10), element("Airline", 210, 10),
        element("1", 10, 40), element("91017675825", 110, 40), element("WY", 210, 40),
        element("2", 10, 70), element("91017676551", 110, 70), element("WY", 210, 70),
    ]
    patch = TableOCRExtractor().extract(
        elements, approved_table_schema(), patch_id="p1", source_region="r1",
    )

    assert patch.completeness_status == "COMPLETE"
    assert patch.rows[0].cells["stt"].value == "1"
    assert patch.rows[0].cells["mawb"].value == "91017675825"
    assert patch.rows[0].cells["airline"].value == "WY"
    assert patch.rows[0].row_type == "DATA_ROW"


def test_table_ocr_keeps_group_row_separate_from_data_completeness():
    elements = [
        element("STT", 10, 10), element("MAWB", 110, 10), element("Airline", 210, 10),
        element("WY", 210, 40), element("OMAN", 240, 40),
        element("1", 10, 70), element("91017675825", 110, 70), element("WY", 210, 70),
    ]
    patch = TableOCRExtractor().extract(
        elements, approved_table_schema(), patch_id="p1",
    )

    assert patch.rows[0].row_type == "AIRLINE_GROUP_ROW"
    assert patch.completeness_status == "COMPLETE"
