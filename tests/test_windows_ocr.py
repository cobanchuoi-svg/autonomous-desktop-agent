"""
Unit tests for Windows.Media.Ocr Native OCR Engine.
"""

from PIL import Image, ImageDraw
import pytest
from agent.vision.factory import create_ocr_processor
from agent.vision.windows_ocr import WindowsMediaOCRProcessor


def test_windows_ocr_factory():
    ocr = create_ocr_processor("windows")
    assert isinstance(ocr, WindowsMediaOCRProcessor)
    assert ocr.is_available() is True


def test_windows_ocr_extract_text():
    ocr = create_ocr_processor("windows")
    img = Image.new("RGB", (400, 80), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 25), "OK CANCEL SUBMIT", fill=(0, 0, 0))

    data = ocr.extract_text(img)
    assert "elements" in data
    assert "full_text" in data
    assert len(data["elements"]) > 0
    assert data["engine"] == "windows_media_ocr"

    # Test clean text
    cleaned = ocr.clean_text("  hello   world  \n")
    assert cleaned == "hello world"


def test_windows_ocr_find_elements():
    ocr = create_ocr_processor("windows")
    img = Image.new("RGB", (400, 80), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 25), "Settings", fill=(0, 0, 0))

    elements = ocr.find_ui_elements(img, "Settings")
    assert len(elements) > 0
    el = elements[0]
    assert "setting" in el.text.lower()
    assert el.center_x > 0
    assert el.center_y > 0
