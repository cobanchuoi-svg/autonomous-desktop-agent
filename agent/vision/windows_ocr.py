"""
Windows Native OCR Processor using Windows.Media.Ocr (WinRT).
Blazing-fast (15-30ms) local OCR built directly into Windows 10/11.
Requires zero external AI models, zero GPU, and consumes minimal RAM.
"""

import time
from typing import Any, Dict, List, Optional
from PIL import Image

from agent.core.exceptions import OCRException, OCRUnavailableError
from agent.vision.base import BaseOCRProcessor
from agent.vision.parser import UIElement, find_elements_by_text
from agent.logger import logger

try:
    import winrt.windows.media.ocr as winrt_ocr
    import winrt.windows.graphics.imaging as winrt_imaging
    import winrt.windows.storage.streams as winrt_streams
    WINRT_OCR_AVAILABLE = True
except ImportError:
    WINRT_OCR_AVAILABLE = False
    winrt_ocr = None
    winrt_imaging = None
    winrt_streams = None


class WindowsMediaOCRProcessor(BaseOCRProcessor):
    """
    Native Windows OCR engine running through Windows Runtime APIs.
    Executes in ~20-40ms on standard desktop CPU.
    """

    def __init__(self, language_tag: Optional[str] = None):
        self.language_tag = language_tag
        self._engine = None

    def is_available(self) -> bool:
        if not WINRT_OCR_AVAILABLE:
            return False
        try:
            langs = winrt_ocr.OcrEngine.available_recognizer_languages
            return len(langs) > 0
        except Exception:
            return False

    def _ensure_engine(self):
        if self._engine is not None:
            return self._engine
        if not self.is_available():
            raise OCRUnavailableError("Windows.Media.Ocr is not available on this system.")

        if self.language_tag:
            import winrt.windows.globalization as winrt_glob
            lang = winrt_glob.Language(self.language_tag)
            self._engine = winrt_ocr.OcrEngine.try_create_from_language(lang)

        if self._engine is None:
            self._engine = winrt_ocr.OcrEngine.try_create_from_user_profile_languages()

        if self._engine is None:
            langs = winrt_ocr.OcrEngine.available_recognizer_languages
            if langs:
                self._engine = winrt_ocr.OcrEngine.try_create_from_language(langs[0])

        if self._engine is None:
            raise OCRException("Failed to initialize Windows.Media.Ocr engine.")

        logger.info(f"[WindowsOCR] Initialized with language: {self._engine.recognizer_language.display_name}")
        return self._engine

    def extract_text(self, image: Image.Image) -> Dict[str, Any]:
        """Run native Windows OCR on PIL Image and extract UI elements with bounding boxes."""
        t0 = time.perf_counter()
        engine = self._ensure_engine()

        # Convert image to RGBA if not already
        if image.mode != "RGBA":
            img_rgba = image.convert("RGBA")
        else:
            img_rgba = image

        # WinRT SoftwareBitmap requires BGRA byte order
        r, g, b, a = img_rgba.split()
        bgra_img = Image.merge("RGBA", (b, g, r, a))
        raw_bytes = bgra_img.tobytes()

        writer = winrt_streams.DataWriter()
        writer.write_bytes(raw_bytes)
        buffer = writer.detach_buffer()

        software_bitmap = winrt_imaging.SoftwareBitmap.create_copy_from_buffer(
            buffer,
            winrt_imaging.BitmapPixelFormat.BGRA8,
            img_rgba.width,
            img_rgba.height,
            winrt_imaging.BitmapAlphaMode.PREMULTIPLIED
        )

        # Execute OCR synchronously through WinRT get()
        async_op = engine.recognize_async(software_bitmap)
        ocr_result = async_op.get()

        elements: List[UIElement] = []
        lines_text: List[str] = []

        for line in ocr_result.lines:
            line_str = line.text.strip()
            if line_str:
                lines_text.append(line_str)
            for word in line.words:
                w_text = word.text.strip()
                if not w_text:
                    continue
                box = word.bounding_rect
                x_min = int(box.x)
                y_min = int(box.y)
                x_max = int(box.x + box.width)
                y_max = int(box.y + box.height)
                center_x = (x_min + x_max) // 2
                center_y = (y_min + y_max) // 2

                elements.append(
                    UIElement(
                        text=w_text,
                        confidence=1.0,
                        bbox=(x_min, y_min, x_max, y_max),
                        center_x=center_x,
                        center_y=center_y,
                        source="windows_ocr",
                        surface="desktop",
                    )
                )

        full_text = ocr_result.text or "\n".join(lines_text)
        duration_ms = (time.perf_counter() - t0) * 1000

        logger.debug(f"[WindowsOCR] Extracted {len(elements)} words ({len(full_text)} chars) in {duration_ms:.2f}ms")

        return {
            "full_text": full_text,
            "elements": elements,
            "lines": lines_text,
            "engine": "windows_media_ocr",
            "duration_ms": duration_ms,
        }

    def clean_text(self, text: str) -> str:
        """Normalize whitespace in OCR output."""
        return " ".join(text.split()).strip()

    def find_ui_elements(self, image: Image.Image, query: str) -> List[UIElement]:
        """Locate UI elements on screen matching query string."""
        data = self.extract_text(image)
        elements = data.get("elements", [])
        return find_elements_by_text(elements, query)
