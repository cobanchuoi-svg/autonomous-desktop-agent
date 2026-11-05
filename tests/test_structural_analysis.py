from agent.brain.brain_client import BrainClient
from agent.brain.spatial_mapping import (
    MappingStatus,
    ScreenType,
    SpatialElement,
    map_column_boundaries,
    map_label_values,
)
from agent.brain.structural_analysis import DecisionStatus, analyze_file_structure
from agent.llm.mock_provider import MockLLMProvider


def _table(headers=("Name", "Amount")):
    return [
        SpatialElement.from_bbox(headers[0], (10, 10, 80, 30)),
        SpatialElement.from_bbox(headers[1], (120, 10, 190, 30)),
        SpatialElement.from_bbox("Alice", (10, 45, 80, 65)),
        SpatialElement.from_bbox("10", (120, 45, 190, 65)),
    ]


def test_per_file_contexts_are_independent():
    first = analyze_file_structure(_table(), file_id="one")
    second = analyze_file_structure(_table(("Code", "Total")), file_id="two")

    assert first.status is DecisionStatus.PASS
    assert [header.name for header in first.headers] == ["Name", "Amount"]
    assert [header.name for header in second.headers] == ["Code", "Total"]
    assert first.file_id != second.file_id


def test_pass_and_schema_drift_decisions():
    result = analyze_file_structure(_table(), expected_headers=["Name", "Amount"])
    drift = analyze_file_structure(_table(), expected_headers=["Code", "Total"])

    assert result.status is DecisionStatus.PASS
    assert result.screen_type is ScreenType.DATA_SCREEN
    assert drift.status is DecisionStatus.SCHEMA_DRIFT
    assert drift.review_reason


def test_low_confidence_header_requires_review():
    elements = _table()
    elements[0] = SpatialElement.from_bbox("Name", (10, 10, 80, 30), confidence=0.2)
    result = analyze_file_structure(elements)
    assert result.status is DecisionStatus.REVIEW_REQUIRED
    assert "confidence" in result.review_reason.lower()


def test_spatial_mapping_uses_angle_and_context():
    label = SpatialElement.from_bbox("Name", (10, 10, 50, 30), context_id="row")
    value = SpatialElement.from_bbox("Alice", (70, 10, 120, 30), context_id="row")
    mapped = map_label_values([label], [value])
    assert mapped.status is MappingStatus.MAPPED
    assert map_column_boundaries([label, value], ScreenType.FORM_SCREEN)[0] == {}


def test_brain_structure_analysis_does_not_call_provider():
    provider = MockLLMProvider()
    provider.generate = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called"))
    result = BrainClient(provider).analyze_file_structure(_table(), file_id="isolated")
    assert result.ai_required is False
    assert result.status is DecisionStatus.PASS


def test_brain_can_analyze_screen_from_ocr_processor_without_ai():
    class LocalOCR:
        def extract_text(self, image):
            return {"elements": _table(), "engine": "local-test"}

    provider = MockLLMProvider()
    provider.generate = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called"))
    result = BrainClient(provider).analyze_screen(object(), LocalOCR(), file_id="screen-01")
    assert result.status is DecisionStatus.PASS
    assert result.file_id == "screen-01"
    assert result.ai_required is False


def test_multiple_visible_files_keep_independent_contexts():
    client = BrainClient(MockLLMProvider())
    results = client.analyze_files_independently(
        {
            "wps": {"elements": _table(("Name", "Amount"))},
            "pdf": {"elements": _table(("Code", "Total"))},
        },
        expected_headers={
            "wps": ["Name", "Amount"],
            "pdf": ["Code", "Total"],
        },
    )
    assert results["wps"].status is DecisionStatus.PASS
    assert results["pdf"].status is DecisionStatus.PASS
    assert [header.name for header in results["wps"].headers] != [
        header.name for header in results["pdf"].headers
    ]
