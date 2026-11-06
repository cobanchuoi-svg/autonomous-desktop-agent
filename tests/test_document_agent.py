import pytest
from PIL import Image

from agent.brain.brain_client import BrainClient
from agent.brain.spatial_mapping import SpatialElement
from agent.core.document_agent import DocumentAgent, DocumentEyes, DocumentHands
from agent.llm.mock_provider import MockLLMProvider


class FakeCapture:
    def capture_frame(self):
        return object()


class FakeOCR:
    last_frame = None

    def extract_text(self, frame):
        self.last_frame = frame
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
    assert isinstance(agent.eyes, DocumentEyes)
    assert isinstance(agent.hands, DocumentHands)


@pytest.mark.asyncio
async def test_image_scan_ocr_reads_file_not_photo_viewer_toolbar(tmp_path):
    image_path = tmp_path / "source.jpg"
    Image.new("RGB", (20, 20), "white").save(image_path)
    ocr = FakeOCR()
    agent = DocumentAgent(
        capture=FakeCapture(),
        ocr=ocr,
        brain=BrainClient(MockLLMProvider()),
        window_controller=FakeWindowController(),
    )
    result = await agent.scan(str(image_path))
    assert result.success
    assert getattr(ocr.last_frame, "size", None) == (20, 20)

@pytest.mark.asyncio
async def test_pdf_scan_in_memory_renders_pdf_directly(tmp_path):
    pdf_path = tmp_path / "test_doc.pdf"
    img1 = Image.new("RGB", (60, 60), "white")
    img2 = Image.new("RGB", (60, 60), "white")
    img1.save(pdf_path, "PDF", save_all=True, append_images=[img2])

    ocr = FakeOCR()
    agent = DocumentAgent(
        capture=FakeCapture(),
        ocr=ocr,
        brain=BrainClient(MockLLMProvider()),
        window_controller=FakeWindowController(),
    )
    result = await agent.scan(str(pdf_path))
    assert result.success
    assert result.ocr.get("pages") == 2
    assert getattr(ocr.last_frame, "size", None) is not None
