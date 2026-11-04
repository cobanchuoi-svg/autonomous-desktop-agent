"""
Unit tests for Screen Capture, OCR normalization, and UI element parsing.
"""

from PIL import Image, ImageDraw
import pytest

from agent.core.exceptions import OCRUnavailableError
from agent.vision.capture import ScreenCapture
from agent.vision.ocr import OCRProcessor, PADDLE_AVAILABLE
from agent.vision.ocr_worker import _ocr_subprocess_worker, IsolatedOCRClient
from agent.vision.parser import UIElement, find_elements_by_text


def test_screen_capture_and_dimensions():
    capture = ScreenCapture()
    monitors = capture.get_monitors()
    assert len(monitors) >= 1

    frame = capture.capture_frame()
    assert isinstance(frame, Image.Image)
    assert frame.width > 0
    assert frame.height > 0


def test_ui_element_bounding_box_center():
    quad = [[100, 200], [200, 200], [200, 250], [100, 250]]
    element = UIElement.from_quad("OK Button", confidence=0.95, quad=quad)
    assert element.center_x == 150
    assert element.center_y == 225
    assert element.bbox == (100, 200, 200, 250)


def test_find_elements_by_text():
    elements = [
        UIElement(text="File", confidence=0.99, bbox=(0, 0, 10, 10), center_x=5, center_y=5),
        UIElement(text="Save As", confidence=0.95, bbox=(0, 10, 10, 20), center_x=5, center_y=15),
        UIElement(text="Open File", confidence=0.92, bbox=(0, 20, 10, 30), center_x=5, center_y=25),
    ]

    matches = find_elements_by_text(elements, "file", case_sensitive=False, exact_match=False)
    assert len(matches) == 2  # "File" and "Open File"

    exact = find_elements_by_text(elements, "File", case_sensitive=True, exact_match=True)
    assert len(exact) == 1
    assert exact[0].text == "File"


def test_ocr_processor_clean_text():
    ocr = OCRProcessor()
    dirty = "  Hello \t World \r\n This is   OCR.  "
    cleaned = ocr.clean_text(dirty)
    assert cleaned == "Hello World This is OCR."


def test_ocr_raises_when_unavailable_and_never_fabricates():
    """Verify that OCR never injects synthetic placeholders and raises OCRUnavailableError."""
    ocr = OCRProcessor()
    dummy_img = Image.new("RGB", (100, 100), color=(255, 255, 255))

    if not ocr.is_available():
        with pytest.raises(OCRUnavailableError) as exc_info:
            ocr.extract_text(dummy_img)
        assert "PaddleOCR is not installed" in str(exc_info.value)
    else:
        result = ocr.extract_text(dummy_img)
        # Real OCR on plain blank image should not contain synthetic 'Chrome' or 'Visual Studio Code'
        assert "Chrome" not in result["text"]
        assert "Visual Studio Code" not in result["text"]


def test_ocr_diagnostics_and_versions():
    """Verify OCR diagnostics structure and version detection."""
    from agent.vision.ocr import get_paddle_versions
    versions = get_paddle_versions()
    assert isinstance(versions, dict)
    assert "paddle" in versions
    assert "paddleocr" in versions
    assert "api_generation" in versions

    ocr = OCRProcessor()
    diag = ocr.get_diagnostics()
    assert isinstance(diag, dict)
    assert "status" in diag
    assert "api_generation" in diag


def test_ocr_processes_real_screenshot():
    """Requirement 8: Verify OCR can process a real screenshot."""
    capture = ScreenCapture()
    frame = capture.capture_frame()
    assert isinstance(frame, Image.Image)

    ocr = OCRProcessor()
    if ocr.is_available():
        res = ocr.extract_text(frame)
        assert isinstance(res, dict)
        assert "text" in res
        assert "full_text" in res
        assert "elements" in res
        # UI elements must be instances of UIElement
        for el in res["elements"]:
            assert isinstance(el, UIElement)
            assert el.confidence >= 0.0
    else:
        with pytest.raises(OCRUnavailableError):
            ocr.extract_text(frame)

