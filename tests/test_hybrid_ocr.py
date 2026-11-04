"""
Unit tests for Hybrid OCR Processor (Windows OCR + Gemini Vision Fallback).
"""

from unittest.mock import MagicMock
from PIL import Image
import pytest

from agent.vision.factory import create_ocr_processor
from agent.vision.gemini_ocr import GeminiVisionOCRProcessor
from agent.vision.hybrid_ocr import HybridOCRProcessor
from agent.vision.parser import UIElement


def test_ocr_factory_options():
    # 1. Default should be hybrid
    h = create_ocr_processor("hybrid")
    assert isinstance(h, HybridOCRProcessor)

    # 2. Gemini vision
    g = create_ocr_processor("gemini")
    assert isinstance(g, GeminiVisionOCRProcessor)


def test_gemini_vision_ocr_unit():
    ocr = GeminiVisionOCRProcessor(api_key="AQ.TestKey123")
    assert ocr.is_available() is True
    assert ocr.clean_text("  abc   def \n") == "abc def"

    # Test image bytes preparation
    img = Image.new("RGB", (200, 100), color=(255, 0, 0))
    b64 = ocr._prepare_image_bytes(img)
    assert isinstance(b64, str)
    assert len(b64) > 10


def test_hybrid_ocr_primary_success():
    img = Image.new("RGB", (100, 50), color=(255, 255, 255))
    mock_primary = MagicMock()
    mock_primary.is_available.return_value = True
    mock_primary.extract_text.return_value = {
        "full_text": "HELLO",
        "elements": [UIElement(text="HELLO", bbox=(0, 0, 10, 10), center_x=5, center_y=5)],
        "engine": "windows_media_ocr",
    }
    mock_fallback = MagicMock()

    hybrid = HybridOCRProcessor(primary=mock_primary, fallback=mock_fallback)
    result = hybrid.extract_text(img)

    assert "HELLO" in result["full_text"]
    assert "hybrid" in result["engine"]
    # Fallback should NOT have been called
    mock_fallback.extract_text.assert_not_called()


def test_hybrid_ocr_fallback_on_empty():
    img = Image.new("RGB", (100, 50), color=(255, 255, 255))
    mock_primary = MagicMock()
    mock_primary.is_available.return_value = True
    # Primary finds nothing
    mock_primary.extract_text.return_value = {
        "full_text": "",
        "elements": [],
        "engine": "windows_media_ocr",
    }

    mock_fallback = MagicMock()
    mock_fallback.is_available.return_value = True
    mock_fallback.extract_text.return_value = {
        "full_text": "GEMINI_SEES_THIS",
        "elements": [UIElement(text="GEMINI_SEES_THIS", bbox=(0, 0, 10, 10), center_x=5, center_y=5)],
        "engine": "gemini_vision",
    }

    hybrid = HybridOCRProcessor(primary=mock_primary, fallback=mock_fallback)
    result = hybrid.extract_text(img)

    assert result["full_text"] == "GEMINI_SEES_THIS"
    assert "fallback" in result["engine"]
    mock_fallback.extract_text.assert_called_once()
