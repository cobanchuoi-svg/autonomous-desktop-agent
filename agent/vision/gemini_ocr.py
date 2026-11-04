"""
Gemini Vision OCR Processor using Google Gemini Multimodal REST API.
Extracts visible text, lines, and bounding boxes directly from screen captures.
"""

import base64
import io
import json
import time
from typing import Any, Dict, List, Optional
import httpx
from PIL import Image

from agent.config import settings
from agent.logger import logger
from agent.vision.base import BaseOCRProcessor
from agent.vision.parser import UIElement, find_elements_by_text


class GeminiVisionOCRProcessor(BaseOCRProcessor):
    """
    Cloud Multimodal OCR using Gemini 2.0 Flash / 1.5 Flash.
    Provides deep semantic visual understanding and bounding box localization.
    """

    SYSTEM_PROMPT = (
        "You are a precise screen OCR and UI element parser. "
        "Extract all readable text, labels, and buttons from the provided screenshot. "
        "Return strict JSON with fields:\n"
        "- full_text: full text content as a single string with linebreaks\n"
        "- lines: list of strings, each representing a logical text line\n"
        "- elements: list of objects: {\"text\": \"label\", \"box_2d\": [ymin, xmin, ymax, xmax]} "
        "where coordinates are normalized integers between 0 and 1000."
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 15.0,
    ):
        if api_key:
            self.api_key = api_key.strip()
        else:
            self.api_key = (
                getattr(settings.llm, "gemini_api_key", "")
                or getattr(settings.llm, "api_key", "")
                or ""
            ).strip()
        self.model_name = model_name or settings.llm.model_name or "gemini-2.0-flash"
        self.timeout = timeout
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def is_available(self) -> bool:
        """Check if Gemini API key is configured."""
        return bool(self.api_key)

    def _prepare_image_bytes(self, image: Image.Image, max_dim: int = 1600, quality: int = 80) -> str:
        """Resize if oversized and encode to Base64 JPEG string."""
        img = image.copy()
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Downscale proportionally if larger than max_dim to reduce latency and token usage
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def extract_text(self, image: Image.Image) -> Dict[str, Any]:
        """Extract text and UI elements using Gemini Vision REST API synchronously."""
        t0 = time.perf_counter()
        if not self.is_available():
            logger.warning("[GeminiVisionOCR] API key not available; cannot perform vision request.")
            return {"full_text": "", "elements": [], "lines": [], "engine": "gemini_vision", "duration_ms": 0.0}

        orig_w, orig_h = image.size
        b64_image = self._prepare_image_bytes(image)

        url = f"{self.base_url}/{self.model_name}:generateContent?key={self.api_key}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": "Extract all readable text and interactive UI elements from this screenshot. Output JSON only."},
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": b64_image,
                            }
                        },
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": self.SYSTEM_PROMPT}]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
                "maxOutputTokens": 2048,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code != 200:
                    logger.warning(f"[GeminiVisionOCR] HTTP {res.status_code}: {res.text[:200]}")
                    return {"full_text": "", "elements": [], "lines": [], "engine": "gemini_vision", "error": f"HTTP {res.status_code}"}

                data = res.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return {"full_text": "", "elements": [], "lines": [], "engine": "gemini_vision"}

                parts = candidates[0].get("content", {}).get("parts", [])
                raw_text = "".join(p.get("text", "") for p in parts).strip()
                if not raw_text:
                    return {"full_text": "", "elements": [], "lines": [], "engine": "gemini_vision"}

                parsed = json.loads(raw_text)
                full_text = parsed.get("full_text", "")
                lines = parsed.get("lines", [])
                raw_elements = parsed.get("elements", [])

                elements: List[UIElement] = []
                for el in raw_elements:
                    txt = str(el.get("text", "")).strip()
                    if not txt:
                        continue
                    box_2d = el.get("box_2d", [])
                    if len(box_2d) == 4:
                        ymin, xmin, ymax, xmax = box_2d
                        # Denormalize 0-1000 coordinates to actual pixel dimensions
                        px_xmin = int((xmin / 1000.0) * orig_w)
                        px_ymin = int((ymin / 1000.0) * orig_h)
                        px_xmax = int((xmax / 1000.0) * orig_w)
                        px_ymax = int((ymax / 1000.0) * orig_h)
                    else:
                        px_xmin, px_ymin, px_xmax, px_ymax = 0, 0, 0, 0

                    center_x = (px_xmin + px_xmax) // 2
                    center_y = (px_ymin + px_ymax) // 2

                    elements.append(
                        UIElement(
                            text=txt,
                            confidence=0.95,
                            bbox=(px_xmin, px_ymin, px_xmax, px_ymax),
                            center_x=center_x,
                            center_y=center_y,
                            source="gemini_vision",
                            surface="desktop",
                        )
                    )

                duration_ms = (time.perf_counter() - t0) * 1000
                logger.info(f"[GeminiVisionOCR] Extracted {len(elements)} elements ({len(full_text)} chars) in {duration_ms:.1f}ms")

                return {
                    "full_text": full_text,
                    "elements": elements,
                    "lines": lines,
                    "engine": "gemini_vision",
                    "duration_ms": duration_ms,
                }
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000
            logger.warning(f"[GeminiVisionOCR] Vision extraction failed: {exc}")
            return {
                "full_text": "",
                "elements": [],
                "lines": [],
                "engine": "gemini_vision",
                "error": str(exc),
                "duration_ms": duration_ms,
            }

    def clean_text(self, text: str) -> str:
        return " ".join(text.split()).strip()

    def find_ui_elements(self, image: Image.Image, query: str) -> List[UIElement]:
        data = self.extract_text(image)
        elements = data.get("elements", [])
        return find_elements_by_text(elements, query)
