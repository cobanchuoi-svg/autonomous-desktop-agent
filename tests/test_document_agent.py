import pytest

from agent.brain.brain_client import BrainClient
from agent.brain.spatial_mapping import SpatialElement
from agent.core.document_agent import DocumentAgent
from agent.llm.mock_provider import MockLLMProvider


class FakeCapture:
    def capture_frame(self):
        return object()


class FakeOCR:
    def extract_text(self, frame):
        return {
            "full_text": "Name Amount Alice 10",
            "elements": [
                SpatialElement.from_bbox("Name", (10, 10, 80, 30)),
                SpatialElement.from_bbox("Amount", (120, 10, 190, 30)),
                SpatialElement.from_bbox("Alice", (10, 45, 80, 65)),
                SpatialElement.from_bbox("10", (120, 45, 190, 65)),
            ],
        }


class FakeWindowController:
    def prepare_foreground_document(self, path, *, wps_title):
        return type("Layout", (), {"success": True, "reason": "", "document_title": path})()


@pytest.mark.asyncio
async def test_document_agent_unifies_layout_eyes_ocr_and_brain():
    agent = DocumentAgent(
        capture=FakeCapture(),
        ocr=FakeOCR(),
        brain=BrainClient(MockLLMProvider()),
        window_controller=FakeWindowController(),
    )
    result = await agent.scan("scan.pdf")
    assert result.success
    assert result.analysis.status.value == "PASS"
    assert result.analysis.ai_required is False
