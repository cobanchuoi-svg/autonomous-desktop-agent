"""Optional Florence-2 OCR backend returning text with quadrilateral regions."""

import importlib.util
import re
import time
from typing import Any, Dict, List

from PIL import Image

from agent.core.exceptions import OCRUnavailableError
from agent.vision.base import BaseOCRProcessor
from agent.vision.parser import UIElement, find_elements_by_text


class Florence2OCRProcessor(BaseOCRProcessor):
    TASK = "<OCR_WITH_REGION>"

    def __init__(self, model_name: str = "microsoft/Florence-2-base", device: str | None = None):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._processor = None
        self._torch = None
        self._model_load_seconds = 0.0

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("torch") is not None and importlib.util.find_spec("transformers") is not None

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.is_available():
            raise OCRUnavailableError("Florence-2 OCR requires optional dependencies: pip install torch transformers")
        try:
            load_started = time.perf_counter()
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor

            self._torch = torch
            self.device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
            dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
            self._processor = AutoProcessor.from_pretrained(self.model_name, trust_remote_code=True)
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_name, torch_dtype=dtype, trust_remote_code=True
            ).to(self.device).eval()
            self._model_load_seconds = time.perf_counter() - load_started
        except Exception as exc:
            raise OCRUnavailableError(f"Could not initialize Florence-2 OCR: {exc}") from exc

    def clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def extract_text(self, image: Image.Image) -> Dict[str, Any]:
        self._load()
        started = time.perf_counter()
        rgb = image.convert("RGB")
        inputs = self._processor(text=self.TASK, images=rgb, return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            generated = self._model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=1024,
                num_beams=1,
                do_sample=False,
            )
        decoded = self._processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = self._processor.post_process_generation(decoded, task=self.TASK, image_size=rgb.size)
        region = parsed.get(self.TASK, {}) if isinstance(parsed, dict) else {}
        labels = region.get("labels", [])
        boxes = region.get("quad_boxes", [])
        elements: List[UIElement] = []
        for label, flat_box in zip(labels, boxes):
            text = self.clean_text(label)
            if not text or len(flat_box) < 8:
                continue
            quad = [[float(flat_box[i]), float(flat_box[i + 1])] for i in range(0, 8, 2)]
            elements.append(UIElement.from_quad(text=text, confidence=0.0, quad=quad, source="florence2"))
        elements.sort(key=lambda item: (item.center_y, item.bbox[0]))
        texts = [element.text for element in elements]
        return {
            "text": texts,
            "full_text": " | ".join(texts),
            "elements": elements,
            "metadata": {
                "backend": "florence2",
                "model": self.model_name,
                "device": self.device,
                "model_load_seconds": self._model_load_seconds,
                "inference_seconds": time.perf_counter() - started,
            },
        }

    def find_ui_elements(self, image: Image.Image, query: str) -> List[UIElement]:
        return find_elements_by_text(self.extract_text(image)["elements"], query)
