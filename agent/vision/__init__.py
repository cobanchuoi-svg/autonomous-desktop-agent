"""
Vision and OCR processing package.
"""

from agent.vision.capture import ScreenCapture
from agent.vision.windows_ocr import WindowsMediaOCRProcessor
from agent.vision.parser import UIElement, find_elements_by_text


def __getattr__(name: str):
    if name == "OCRProcessor":
        from agent.vision.ocr import OCRProcessor
        return OCRProcessor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ScreenCapture",
    "WindowsMediaOCRProcessor",
    "OCRProcessor",
    "UIElement",
    "find_elements_by_text",
]
