"""
OCR processing pipeline using PaddleOCR with preprocessing, multi-version compatibility, and error recovery.
Supports both PaddleOCR 2.x and PaddleOCR 3.x (PaddleX architecture).
"""

import inspect
import hashlib
import os
import re
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from PIL import Image

from agent.core.exceptions import OCRException, OCRUnavailableError
from agent.vision.base import BaseOCRProcessor
from agent.vision.parser import UIElement, find_elements_by_text
from agent.logger import logger

# Lazy PaddleOCR import
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False
    PaddleOCR = None


def get_paddle_versions() -> Dict[str, Any]:
    """Retrieve installed PaddlePaddle and PaddleOCR versions and detected API generation."""
    info = {
        "paddle": "not installed",
        "paddleocr": "not installed",
        "api_generation": "none",
        "available": False,
    }
    try:
        import paddle
        info["paddle"] = getattr(paddle, "__version__", "unknown")
    except ImportError:
        pass

    try:
        import paddleocr
        ver = getattr(paddleocr, "__version__", "unknown")
        info["paddleocr"] = ver
        info["available"] = True

        # Check API signature on PaddleOCR class
        if hasattr(paddleocr, "PaddleOCR"):
            sig = inspect.signature(paddleocr.PaddleOCR.__init__)
            if (
                "use_textline_orientation" in sig.parameters
                or "use_doc_orientation_classify" in sig.parameters
                or "ocr_version" in sig.parameters
                or "text_detection_model_name" in sig.parameters
            ):
                info["api_generation"] = "v3 (PaddleX)"
            elif "use_gpu" in sig.parameters:
                info["api_generation"] = "v2 (Legacy)"
            else:
                info["api_generation"] = "v3" if hasattr(paddleocr, "DocUnderstanding") else "v2"
    except ImportError:
        pass

    return info


def create_paddle_engine(lang: str = "en", use_gpu: bool = False) -> Any:
    """
    Instantiate PaddleOCR with compatibility handling for multiple versions:
    - PaddleOCR 3.x: requires `device='gpu'|'cpu'`, `use_textline_orientation`, rejects `use_gpu`.
    - PaddleOCR 2.x: requires `use_gpu=bool`, `use_angle_cls=bool`.
    """
    if not PADDLE_AVAILABLE or PaddleOCR is None:
        raise OCRUnavailableError(
            "PaddleOCR is not installed or available on this system. "
            "Autonomous vision execution refused."
        )

    sig = inspect.signature(PaddleOCR.__init__)
    params = sig.parameters
    device_str = "gpu" if use_gpu else "cpu"

    # Detect PaddleOCR 3.x (PaddleX architecture)
    is_v3 = (
        "use_textline_orientation" in params
        or "use_doc_orientation_classify" in params
        or "ocr_version" in params
        or "text_detection_model_name" in params
    )

    if is_v3:
        # PaddleOCR 3.x (PaddleX architecture)
        # Note: Screens are upright 2D desktop displays, so we disable document unwarping & orientation classify
        init_kwargs = {
            "lang": lang,
            "device": device_str,
            "use_textline_orientation": True,
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
        }
        # In PaddlePaddle 3.x CPU inference on Windows, OneDNN has a known PIR conversion bug
        # Disabling enable_mkldnn ensures deterministic, bug-free CPU inference
        if not use_gpu:
            init_kwargs["enable_mkldnn"] = False

        logger.info(f"[OCR] Initializing PaddleOCR 3.x (device={device_str}, lang={lang})")
        return PaddleOCR(**init_kwargs)

    elif "use_gpu" in params:
        # PaddleOCR 2.x (Legacy API)
        init_kwargs = {
            "lang": lang,
            "use_gpu": use_gpu,
            "use_angle_cls": True,
        }
        if "show_log" in params:
            init_kwargs["show_log"] = False
        logger.info(f"[OCR] Initializing PaddleOCR 2.x (use_gpu={use_gpu}, lang={lang})")
        return PaddleOCR(**init_kwargs)

    else:
        # Generic fallback
        logger.info(f"[OCR] Initializing PaddleOCR with default parameters (lang={lang})")
        try:
            return PaddleOCR(lang=lang)
        except Exception:
            return PaddleOCR()


def parse_ocr_results(raw_results: Any, clean_func) -> Tuple[List[str], List[UIElement]]:
    """
    Parse OCR results flexibly across both PaddleOCR 2.x and 3.x structures.
    - 3.x: list of dicts with 'rec_texts', 'rec_scores', and 'rec_polys' (or 'rec_boxes')
    - 2.x: list of lines: [[ [box_4_pts, (text, conf)], ... ]]
    """
    raw_text_list: List[str] = []
    ui_elements: List[UIElement] = []

    if not raw_results:
        return raw_text_list, ui_elements

    # Check for PaddleOCR 3.x dictionary structure
    first = raw_results[0] if isinstance(raw_results, (list, tuple)) and len(raw_results) > 0 else raw_results
    if isinstance(first, dict) and "rec_texts" in first:
        items = raw_results if isinstance(raw_results, list) else [raw_results]
        for res_dict in items:
            rec_texts = res_dict.get("rec_texts", [])
            rec_scores = res_dict.get("rec_scores", [])
            rec_polys = res_dict.get("rec_polys")
            if rec_polys is None:
                rec_polys = res_dict.get("dt_polys", [])

            for i, text in enumerate(rec_texts):
                cleaned = clean_func(text)
                if not cleaned:
                    continue
                conf = float(rec_scores[i]) if i < len(rec_scores) else 0.9
                poly = rec_polys[i] if i < len(rec_polys) else None
                if poly is not None and hasattr(poly, "tolist"):
                    poly = poly.tolist()

                raw_text_list.append(cleaned)
                if poly:
                    ui_elements.append(UIElement.from_quad(text=cleaned, confidence=conf, quad=poly))
        return raw_text_list, ui_elements

    # PaddleOCR 2.x line-list structure
    if isinstance(raw_results, (list, tuple)) and len(raw_results) > 0:
        lines = raw_results[0] if isinstance(raw_results[0], (list, tuple)) else raw_results
        if lines and isinstance(lines, (list, tuple)):
            for line in lines:
                if isinstance(line, (list, tuple)) and len(line) == 2:
                    box = line[0]
                    text_conf = line[1]
                    if isinstance(text_conf, (list, tuple)) and len(text_conf) >= 2:
                        text, conf = str(text_conf[0]), float(text_conf[1])
                        cleaned = clean_func(text)
                        if cleaned:
                            raw_text_list.append(cleaned)
                            ui_elements.append(
                                UIElement.from_quad(text=cleaned, confidence=conf, quad=box)
                            )

    return raw_text_list, ui_elements


class OCRProcessor(BaseOCRProcessor):
    """Extracts, cleans, and structures text and UI bounding boxes from screen frames."""

    _HASH_WIDTH = 256
    _DIFF_TILE = 4
    _DIFF_PIXEL_THRESHOLD = 28
    _DIFF_TILE_FRACTION = 0.005
    _DIFF_TILE_MEAN = 2.5
    _MAX_CHANGED_TILE_FRACTION = 0.35
    _MAX_ROI_AREA_FRACTION = 0.40
    _ROI_PADDING = 8

    def __init__(self, lang: str = "en", use_gpu: bool = False, max_retries: int = 3):
        self.lang = lang
        self.use_gpu = use_gpu
        self.max_retries = max_retries
        self._ocr_engine = None
        self._cached_result: Optional[Dict[str, Any]] = None
        self._cached_signature: Optional[bytes] = None
        self._cached_thumbnail: Optional[np.ndarray] = None
        self._cached_size: Optional[Tuple[int, int]] = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if PaddleOCR library is installed and importable."""
        return PADDLE_AVAILABLE

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return diagnostic health status for the OCR subsystem."""
        versions = get_paddle_versions()
        status = "OPERATIONAL" if versions["available"] else "UNAVAILABLE"
        return {
            "status": status,
            "paddle_version": versions["paddle"],
            "paddleocr_version": versions["paddleocr"],
            "api_generation": versions["api_generation"],
            "backend_available": versions["available"],
        }

    def _get_engine(self):
        if not self.is_available():
            raise OCRUnavailableError(
                "PaddleOCR is not installed or available on this system. "
                "Autonomous vision execution refused."
            )
        if self._ocr_engine is None:
            self._ocr_engine = create_paddle_engine(lang=self.lang, use_gpu=self.use_gpu)
        return self._ocr_engine

    def clean_text(self, text: str) -> str:
        """Normalize whitespace, remove invalid unicode control characters."""
        if not text:
            return ""
        # Replace multiple spaces/newlines with single space
        cleaned = re.sub(r"[\r\n\t]+", " ", str(text))
        cleaned = re.sub(r" +", " ", cleaned)
        return cleaned.strip()

    def _image_signature(self, image: Image.Image) -> Tuple[bytes, np.ndarray]:
        """Hash a small grayscale image and return it for change detection."""
        width, height = image.size
        thumb_height = max(1, round(height * self._HASH_WIDTH / max(1, width)))
        thumb = image.convert("L").resize(
            (self._HASH_WIDTH, thumb_height), Image.Resampling.BILINEAR
        )
        pixels = np.asarray(thumb, dtype=np.uint8)
        return hashlib.blake2b(pixels.tobytes(), digest_size=16).digest(), pixels

    @staticmethod
    def _changed_tile_components(mask: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Return connected tile rectangles as (x0, y0, x1, y1), x1/y1 exclusive."""
        rows, cols = mask.shape
        seen = np.zeros(mask.shape, dtype=bool)
        components: List[Tuple[int, int, int, int]] = []
        for y in range(rows):
            for x in range(cols):
                if not mask[y, x] or seen[y, x]:
                    continue
                queue = deque([(y, x)])
                seen[y, x] = True
                min_x = max_x = x
                min_y = max_y = y
                while queue:
                    cy, cx = queue.popleft()
                    min_x, max_x = min(min_x, cx), max(max_x, cx)
                    min_y, max_y = min(min_y, cy), max(max_y, cy)
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if (
                                0 <= ny < rows and 0 <= nx < cols
                                and mask[ny, nx] and not seen[ny, nx]
                            ):
                                seen[ny, nx] = True
                                queue.append((ny, nx))
                components.append((min_x, min_y, max_x + 1, max_y + 1))
        return components

    def _find_change_roi(
        self, previous: np.ndarray, current: np.ndarray, image_size: Tuple[int, int]
    ) -> Tuple[Optional[Tuple[int, int, int, int]], float, bool]:
        """Find a padded ROI; request a full scan when changes are broad/ambiguous."""
        if previous.shape != current.shape:
            return None, 1.0, True

        diff = np.abs(current.astype(np.int16) - previous.astype(np.int16))
        tile = self._DIFF_TILE
        tile_mask = np.zeros(
            (int(np.ceil(diff.shape[0] / tile)), int(np.ceil(diff.shape[1] / tile))),
            dtype=bool,
        )
        for ty in range(tile_mask.shape[0]):
            for tx in range(tile_mask.shape[1]):
                patch = diff[ty * tile:(ty + 1) * tile, tx * tile:(tx + 1) * tile]
                if patch.size == 0:
                    continue
                changed_fraction = float(np.count_nonzero(patch >= self._DIFF_PIXEL_THRESHOLD)) / patch.size
                if changed_fraction >= self._DIFF_TILE_FRACTION and float(patch.mean()) >= self._DIFF_TILE_MEAN:
                    tile_mask[ty, tx] = True

        changed_fraction = float(np.count_nonzero(tile_mask)) / max(1, tile_mask.size)
        if not tile_mask.any():
            return None, changed_fraction, False
        if changed_fraction >= self._MAX_CHANGED_TILE_FRACTION:
            return None, changed_fraction, True

        components = self._changed_tile_components(tile_mask)
        width, height = image_size
        scale_x = width / current.shape[1]
        scale_y = height / current.shape[0]
        pad = self._ROI_PADDING
        boxes = []
        for x0, y0, x1, y1 in components:
            boxes.append((
                max(0, int(x0 * tile * scale_x) - pad),
                max(0, int(y0 * tile * scale_y) - pad),
                min(width, int(x1 * tile * scale_x) + pad),
                min(height, int(y1 * tile * scale_y) + pad),
            ))

        # A single union crop keeps backend/model overhead bounded while preserving
        # all changed regions. Broad unions fall back to a complete scan.
        roi = (
            min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes),
        )
        roi_area = max(0, roi[2] - roi[0]) * max(0, roi[3] - roi[1])
        if roi_area / max(1, width * height) >= self._MAX_ROI_AREA_FRACTION:
            return None, changed_fraction, True
        return roi, changed_fraction, False

    @staticmethod
    def _copy_result(result: Dict[str, Any], **metadata: Any) -> Dict[str, Any]:
        copied = dict(result)
        copied["text"] = list(result.get("text", []))
        copied["elements"] = list(result.get("elements", []))
        copied["metadata"] = dict(result.get("metadata", {}), **metadata)
        return copied

    def _run_backend(self, image: Image.Image) -> Dict[str, Any]:
        """Run one backend OCR pass with the existing compatibility/retry logic."""
        attempts = 0
        last_error = None
        while attempts < self.max_retries:
            try:
                engine = self._get_engine()
                img_array = np.asarray(image.convert("RGB"))
                if hasattr(engine, "predict"):
                    try:
                        results = engine.predict(img_array)
                    except Exception:
                        results = engine.ocr(img_array)
                elif hasattr(engine, "ocr"):
                    try:
                        results = engine.ocr(img_array, cls=True)
                    except TypeError:
                        results = engine.ocr(img_array)
                else:
                    raise OCRException("Loaded OCR engine does not support predict() or ocr()")

                texts, elements = parse_ocr_results(results, self.clean_text)
                return {"text": texts, "full_text": " | ".join(texts), "elements": elements}
            except OCRUnavailableError:
                raise
            except Exception as exc:
                attempts += 1
                last_error = exc
                logger.warning(f"[OCR] Extraction attempt {attempts}/{self.max_retries} failed: {exc}")
                if attempts < self.max_retries:
                    time.sleep(0.5)
        raise OCRException(f"OCR failed after {self.max_retries} attempts: {last_error}")

    @staticmethod
    def _intersects(element: UIElement, roi: Tuple[int, int, int, int]) -> bool:
        x0, y0, x1, y1 = roi
        ex0, ey0, ex1, ey1 = element.bbox
        return ex0 < x1 and ex1 > x0 and ey0 < y1 and ey1 > y0

    def _run_roi_update(
        self, image: Image.Image, roi: Tuple[int, int, int, int], changed_fraction: float
    ) -> Dict[str, Any]:
        assert self._cached_result is not None
        crop = image.crop(roi)
        if len(self._cached_result.get("text", [])) != len(self._cached_result.get("elements", [])):
            raise OCRException("Cached OCR result has unanchored text; require full scan")
        fresh = self._run_backend(crop)
        # Incremental merging requires spatially anchored text from both passes.
        if len(fresh["text"]) != len(fresh["elements"]):
            raise OCRException("ROI OCR returned text without bounding boxes; require full scan")

        old_elements = [
            element for element in self._cached_result.get("elements", [])
            if not self._intersects(element, roi)
        ]
        offset_elements = []
        for element in fresh["elements"]:
            x0, y0, x1, y1 = element.bbox
            quad = [[x0 + roi[0], y0 + roi[1]], [x1 + roi[0], y0 + roi[1]],
                    [x1 + roi[0], y1 + roi[1]], [x0 + roi[0], y1 + roi[1]]]
            offset_elements.append(UIElement.from_quad(element.text, element.confidence, quad))

        merged = old_elements + offset_elements
        merged.sort(key=lambda item: (item.center_y, item.bbox[0]))
        texts = [item.text for item in merged]
        return {
            "text": texts,
            "full_text": " | ".join(texts),
            "elements": merged,
            "metadata": {"mode": "roi", "roi": roi, "changed_fraction": changed_fraction},
        }

    def extract_text(self, image: Image.Image) -> Dict[str, Any]:
        """Hash, diff, and OCR only a localized changed region when safe."""
        if not self.is_available():
            raise OCRUnavailableError(
                "PaddleOCR is not installed or available on this system. "
                "Autonomous vision execution refused."
            )

        started = time.perf_counter()
        signature, thumbnail = self._image_signature(image)
        hash_seconds = time.perf_counter() - started
        if (
            self._cached_result is not None
            and self._cached_signature == signature
            and self._cached_size == image.size
        ):
            result = self._copy_result(
                self._cached_result, mode="unchanged", roi_count=0,
                hash_seconds=hash_seconds, effective_ocr_seconds=0.0,
            )
            return result

        if self._cached_result is not None and self._cached_thumbnail is not None and self._cached_size == image.size:
            roi, changed_fraction, requires_full = self._find_change_roi(
                self._cached_thumbnail, thumbnail, image.size
            )
            if roi is None and not requires_full:
                # Difference was below the text-change threshold (e.g. cursor noise).
                return self._copy_result(
                    self._cached_result, mode="unchanged-noise", roi_count=0,
                    changed_fraction=changed_fraction, hash_seconds=hash_seconds,
                    effective_ocr_seconds=0.0,
                )
            if roi is not None and not requires_full:
                try:
                    result = self._run_roi_update(image, roi, changed_fraction)
                    result["metadata"].update({
                        "roi_count": 1, "hash_seconds": hash_seconds,
                        "effective_ocr_seconds": time.perf_counter() - started,
                    })
                    self._cached_result = result
                    self._cached_signature = signature
                    self._cached_thumbnail = thumbnail
                    self._cached_size = image.size
                    return self._copy_result(result, **result["metadata"])
                except OCRException as exc:
                    logger.info(f"[OCR] Falling back to full scan after ROI pass: {exc}")

        result = self._run_backend(image)
        result["metadata"] = {
            "mode": "full", "roi_count": 0, "hash_seconds": hash_seconds,
            "effective_ocr_seconds": time.perf_counter() - started,
        }
        self._cached_result = result
        self._cached_signature = signature
        self._cached_thumbnail = thumbnail
        self._cached_size = image.size
        return self._copy_result(result, **result["metadata"])

    def find_ui_elements(self, image: Image.Image, query: str) -> List[UIElement]:
        """Convenience method to extract and find matching UI elements in one call."""
        result = self.extract_text(image)
        return find_elements_by_text(result["elements"], query)

