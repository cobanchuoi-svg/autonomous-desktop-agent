"""
Isolated OCR Worker Process.
Executes PaddleOCR / EasyOCR in an independent OS process via multiprocessing,
preventing GIL contention and CPU starvation of the main asyncio event loop.
Conforms to P1 #4 requirement.
"""

import asyncio
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
from typing import Any, Dict, List, Optional
import numpy as np
from PIL import Image

from agent.core.exceptions import OCRException, OCRUnavailableError
from agent.vision.ocr import create_paddle_engine, parse_ocr_results, PADDLE_AVAILABLE
from agent.vision.parser import UIElement
from agent.logger import logger


def _ocr_subprocess_worker(image_bytes: bytes, image_size: tuple[int, int], lang: str = "en") -> Dict[str, Any]:
    """Isolated worker function executed inside a child process."""
    try:
        from PIL import Image
        img = Image.frombytes("RGB", image_size, image_bytes)
        img_arr = np.array(img)

        if not PADDLE_AVAILABLE:
            return {
                "text": [],
                "full_text": "",
                "elements": [],
                "success": False,
                "error": "PaddleOCR is not installed in worker process",
            }

        try:
            engine = create_paddle_engine(lang=lang, use_gpu=False)
            if hasattr(engine, "predict"):
                try:
                    results = engine.predict(img_arr)
                except Exception:
                    results = engine.ocr(img_arr)
            elif hasattr(engine, "ocr"):
                try:
                    results = engine.ocr(img_arr, cls=True)
                except TypeError:
                    results = engine.ocr(img_arr)
            else:
                raise OCRException("Engine does not support predict or ocr")

            texts, raw_elements = parse_ocr_results(results, lambda t: t.strip() if t else "")
            serializable_elements = [
                {
                    "text": el.text,
                    "confidence": el.confidence,
                    "box": el.bbox,
                }
                for el in raw_elements
            ]

            return {
                "text": texts,
                "full_text": " | ".join(texts),
                "elements": serializable_elements,
                "success": True,
            }
        except ImportError:
            return {
                "text": [],
                "full_text": "",
                "elements": [],
                "success": False,
                "error": "PaddleOCR is not installed in worker process",
            }
    except Exception as e:
        return {"text": [], "full_text": "", "elements": [], "success": False, "error": str(e)}


class IsolatedOCRClient:
    """Client for dispatching OCR workloads to an isolated worker process."""

    def __init__(self, lang: str = "en", max_workers: int = 1):
        self.lang = lang
        self._pool: Optional[ProcessPoolExecutor] = None

    def _ensure_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=1,
                mp_context=mp.get_context("spawn"),
            )
            logger.info("[IsolatedOCR] Started dedicated OCR background process pool.")
        return self._pool

    async def extract_text_isolated(self, image: Image.Image) -> Dict[str, Any]:
        """Dispatch image to isolated process and await results asynchronously."""
        pool = self._ensure_pool()
        rgb_img = image.convert("RGB")
        img_bytes = rgb_img.tobytes()
        img_size = rgb_img.size

        loop = asyncio.get_running_loop()
        raw_result = await loop.run_in_executor(
            pool,
            _ocr_subprocess_worker,
            img_bytes,
            img_size,
            self.lang,
        )

        if not raw_result.get("success", False):
            err = raw_result.get("error", "OCR worker execution failed")
            if "PaddleOCR is not installed" in err:
                raise OCRUnavailableError(err)
            raise OCRException(f"OCR worker failed: {err}")

        # Reconstruct UIElement instances from serializable dicts
        elements = [
            UIElement.from_quad(text=e["text"], confidence=e["confidence"], quad=e["box"])
            for e in raw_result.get("elements", [])
            if "box" in e
        ]

        return {
            "text": raw_result.get("text", []),
            "full_text": raw_result.get("full_text", ""),
            "elements": elements,
            "isolated": True,
        }

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None
            logger.info("[IsolatedOCR] Stopped OCR worker process pool.")
