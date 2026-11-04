"""
Hybrid OCR Processor: Ultra-fast Windows Native OCR with automatic Gemini Vision fallback.
Combines sub-30ms offline speed with the deep semantic understanding of Gemini Multimodal Vision.
"""

import time
from typing import Any, Dict, List, Optional
from PIL import Image

from agent.logger import logger
from agent.vision.base import BaseOCRProcessor
from agent.vision.parser import UIElement, find_elements_by_text
from agent.vision.windows_ocr import WindowsMediaOCRProcessor
from agent.vision.gemini_ocr import GeminiVisionOCRProcessor


class HybridOCRProcessor(BaseOCRProcessor):
    """
    Primary: Windows.Media.Ocr (15-30ms CPU offline).
    Fallback: Gemini 2.0 Flash Multimodal Vision (when primary is empty, fails, or cannot locate query).
    """

    def __init__(
        self,
        primary: Optional[BaseOCRProcessor] = None,
        fallback: Optional[BaseOCRProcessor] = None,
    ):
        self.primary = primary or WindowsMediaOCRProcessor()
        self.fallback = fallback or GeminiVisionOCRProcessor()

    def is_available(self) -> bool:
        return self.primary.is_available() or self.fallback.is_available()

    def extract_text(self, image: Image.Image) -> Dict[str, Any]:
        """Try ultra-fast Windows OCR first; fallback to Gemini Vision if empty or failed."""
        t0 = time.perf_counter()

        # 1. Try Primary (Windows OCR)
        if self.primary.is_available():
            try:
                res = self.primary.extract_text(image)
                full_text = res.get("full_text", "").strip()
                elements = res.get("elements", [])
                # If primary successfully found text or elements, return immediately
                if full_text or elements:
                    res["engine"] = f"{res.get('engine', 'primary')}+hybrid"
                    return res
                logger.info("[HybridOCR] Primary OCR detected no text on frame; invoking Gemini Vision fallback...")
            except Exception as e:
                logger.warning(f"[HybridOCR] Primary OCR failed: {e}; falling back to Gemini Vision...")
        else:
            logger.info("[HybridOCR] Primary OCR unavailable; routing directly to Gemini Vision...")

        # 2. Try Fallback (Gemini Vision)
        if self.fallback.is_available():
            res = self.fallback.extract_text(image)
            res["engine"] = f"{res.get('engine', 'fallback')}+fallback"
            return res

        # 3. Both failed/unavailable
        duration_ms = (time.perf_counter() - t0) * 1000
        return {
            "full_text": "",
            "elements": [],
            "lines": [],
            "engine": "hybrid_none",
            "duration_ms": duration_ms,
        }

    def clean_text(self, text: str) -> str:
        return " ".join(text.split()).strip()

    def find_ui_elements(self, image: Image.Image, query: str) -> List[UIElement]:
        """Search UI elements using primary first; fallback to Gemini Vision if query is not located."""
        if self.primary.is_available():
            try:
                elements = self.primary.find_ui_elements(image, query)
                if elements:
                    return elements
            except Exception as e:
                logger.warning(f"[HybridOCR] Primary element search failed: {e}")

        # If not found locally and fallback available, let Gemini Vision inspect the screen
        if self.fallback.is_available():
            logger.info(f"[HybridOCR] Element '{query}' not found via primary OCR. Calling Gemini Vision...")
            return self.fallback.find_ui_elements(image, query)

        return []
